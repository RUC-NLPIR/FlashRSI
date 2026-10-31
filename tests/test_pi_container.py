"""Run the shared container payload in an isolated local process.

This exercises the staged package, request, Snapshot and real HTTP transport.
It does not start Docker or a benchmark verifier.
"""

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from flashrsi.agents.pi_agent import Pi
from flashrsi.core import Snapshot
from flashrsi.integrations import _container_payload


def test_pi_container_payload_installs_only_its_runtime_dependencies(tmp_path):
    agent = Pi({"llm": {"model_name": "openai/test", "api_key": "test-key"}})
    agent._check_container()
    _container_payload._stage(tmp_path, agent, agent.config, "hello")

    requirements = (tmp_path / "requirements.txt").read_text().splitlines()
    assert {line.split("==")[0] for line in requirements} == {"PyYAML", "httpx"}
    assert all("==" in line for line in requirements)
    assert Snapshot.load(tmp_path / "snapshot.json").id == agent.snapshot.id
    assert (tmp_path / "package/flashrsi/agents/pi_agent/__init__.py").is_file()


def test_pi_staged_container_entry_executes_selected_snapshot(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    work = tmp_path / "task"
    work.mkdir()
    (work / "note.txt").write_text("before\n", encoding="utf-8")
    requests = []
    credential = "pi-container-test-credential"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(
                {
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
                            "id": "edit-note",
                            "type": "function",
                            "function": {
                                "name": "edit",
                                "arguments": json.dumps(
                                    {
                                        "path": "note.txt",
                                        "oldText": "before",
                                        "newText": "after",
                                    }
                                ),
                            },
                        }
                    ],
                }
                finish = "tool_calls"
            else:
                message = {
                    "role": "assistant",
                    "content": f"done {credential}",
                }
                finish = "stop"
            response = {
                "choices": [{"message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            }
            content = json.dumps(response).encode()
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
        agent = Pi(
            {
                "name": "pi",
                "timeout": 20,
                "llm": {
                    "model_name": "openai/container-test",
                    "api_key": credential,
                    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                },
            }
        )
        seed = agent.snapshot
        with seed.check_out() as files:
            # Changing executable Snapshot code must change the actual result,
            # not merely the version ID attached by the transport.
            with (files / "runtime/pi_native/__init__.py").open("a") as stream:
                stream.write(
                    "\n_seed_run = run\n"
                    "async def run(*args, **kwargs):\n"
                    "    result = await _seed_run(*args, **kwargs)\n"
                    "    result.output = 'EVOLVED_RUNTIME:' + result.output\n"
                    "    return result\n"
                )
            with (files / "AGENTS.md").open("a") as stream:
                stream.write("\nEVOLVED_PI_INSTRUCTION\n")
            selected = seed.commit(files)
        agent.update(selected)
        _container_payload._stage(payload, agent, agent.config, "Update the note.")
        request_path = payload / "request.json"
        request = json.loads(request_path.read_text())
        # A local process uses a temporary payload path instead of /opt.
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
    assert record["output"] == "EVOLVED_RUNTIME:done [REDACTED]"
    assert record["messages"][0]["snapshot_id"] == selected.id
    assert record["messages"][0]["snapshot_id"] != seed.id
    assert record["usage"]["input"] == 8
    assert record["usage"]["output"] == 4
    assert (work / "note.txt").read_text() == "after\n"
    assert not request_path.exists()
    assert len(requests) == 2
    assert all(not request["request_exists"] for request in requests)
    assert all(
        request["authorization"] == f"Bearer {credential}" for request in requests
    )
    assert "EVOLVED_PI_INSTRUCTION" in json.dumps(requests[0]["body"])
    tool_result = next(
        event for event in record["messages"] if event["type"] == "tool_execution_end"
    )
    assert tool_result["toolName"] == "edit"
    assert not tool_result["isError"]
    assert credential not in output.read_text()
