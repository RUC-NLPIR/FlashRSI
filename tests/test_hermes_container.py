"""Execute the shared container payload without Docker or a benchmark verifier.

The isolated process loads the staged package and selected Hermes Snapshot,
performs real HTTP requests and changes a task file through native Python tools.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from flashrsi.agents.hermes import Hermes
from flashrsi.core import Snapshot
from flashrsi.integrations import _container_payload


def test_hermes_container_declares_only_native_runtime_dependencies(tmp_path):
    agent = Hermes({"llm": {"model_name": "container-test", "api_key": "test-key"}})
    agent._check_container()
    _container_payload._stage(tmp_path, agent, agent.config, "hello")

    requirements = (tmp_path / "requirements.txt").read_text().splitlines()
    assert {line.split("==")[0] for line in requirements} == {
        "PyYAML",
        "httpx",
        "Pillow",
        "regexrs-py",
    }
    assert all("==" in line for line in requirements)
    assert Snapshot.load(tmp_path / "snapshot.json").id == agent.snapshot.id
    assert (tmp_path / "package/flashrsi/agents/hermes/__init__.py").is_file()


def test_hermes_staged_container_executes_selected_snapshot(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    work = tmp_path / "task"
    work.mkdir()
    requests = []
    credential = "hermes-container-test-credential"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                    "request_exists": (payload / "request.json").exists(),
                }
            )
            if len(requests) == 1:
                message = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "write-note",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps(
                                    {
                                        "path": "note.txt",
                                        "content": "native container\n",
                                    }
                                ),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                message = {"role": "assistant", "content": f"done {credential}"}
                finish = "stop"
            content = json.dumps(
                {
                    "choices": [{"message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        agent = Hermes(
            {
                "name": "hermes",
                "timeout": 20,
                "llm": {
                    "model_name": "container-test-model",
                    "api_key": credential,
                    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                },
            }
        )
        seed = agent.snapshot
        with seed.check_out() as files:
            with (files / "runtime/hermes_native/__init__.py").open("a") as stream:
                stream.write(
                    "\n_seed_run = run\n"
                    "async def run(*args, **kwargs):\n"
                    "    result = await _seed_run(*args, **kwargs)\n"
                    "    result.output = 'EVOLVED_HERMES:' + result.output\n"
                    "    return result\n"
                )
            with (files / "SOUL.md").open("a") as stream:
                stream.write("\nEVOLVED_HERMES_IDENTITY\n")
            selected = seed.commit(files)
        agent.update(selected)
        _container_payload._stage(payload, agent, agent.config, "Write the note.")
        request_path = payload / "request.json"
        request = json.loads(request_path.read_text())
        request["snapshot_path"] = str(payload / "snapshot.json")
        request_path.write_text(json.dumps(request))
        output = payload / "trajectory.json"
        process = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import sys, runpy; "
                f"sys.path.insert(0, {str(payload / 'package')!r}); "
                "runpy.run_module('flashrsi.integrations._container', "
                "run_name='__main__', alter_sys=True)",
                str(request_path),
                str(output),
            ],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert process.returncode == 0, process.stderr
    record = json.loads(output.read_text())
    assert record["status"] == "finished", record["error_message"]
    assert record["output"] == "EVOLVED_HERMES:done [REDACTED]"
    assert record["messages"][0]["snapshot_id"] == selected.id
    assert selected.id != seed.id
    assert record["usage"]["input"] == 8
    assert record["usage"]["output"] == 4
    assert (work / "note.txt").read_text() == "native container\n"
    assert not request_path.exists()
    assert len(requests) == 2
    assert all(request["path"] == "/v1/chat/completions" for request in requests)
    assert all(not request["request_exists"] for request in requests)
    assert all(
        request["authorization"] == f"Bearer {credential}" for request in requests
    )
    assert "EVOLVED_HERMES_IDENTITY" in json.dumps(requests[0]["body"])
    tool_message = next(
        message
        for message in requests[-1]["body"]["messages"]
        if message["role"] == "tool"
    )
    assert tool_message["tool_call_id"] == "write-note"
    assert json.loads(tool_message["content"])["verified"] is True
    assert credential not in output.read_text()
