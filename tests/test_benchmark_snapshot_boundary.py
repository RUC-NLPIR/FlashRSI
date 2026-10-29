"""Keep evolved MiniAgent files while replacing AppWorld's task environment.

Docker setup and the model service are fixtures; native MiniAgent execution and
SpreadsheetBench2 task materialization use their real paths. This is not a
workbook accuracy or an AppWorld official-verifier test.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_spreadsheetbench2 import dataset as dataset

from flashrsi import runner
from flashrsi.agents import MiniAgent
from flashrsi.config import load_config
from flashrsi.core import Snapshot, Task
from flashrsi.integrations import _container, _container_payload, appworld


@pytest.fixture
def local_model():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            response = {
                "id": "local-boundary-test",
                "object": "chat.completion",
                "created": 0,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "done"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
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
        yield SimpleNamespace(
            url=f"http://127.0.0.1:{server.server_port}/v1", requests=requests
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_appworld_to_spreadsheet_preserves_evolved_miniagent(
    dataset, local_model, tmp_path, monkeypatch
):
    harbor = pytest.importorskip("flashrsi.integrations.harbor")
    source_config = {
        "name": "miniagent",
        "max_turns": 1,
        "llm": {"model_name": "source-model", "api_key": "source-credential"},
    }
    source = MiniAgent(source_config)
    seed = source.snapshot
    with seed.check_out() as files:
        loop = files / "runtime/agent.py"
        # A visible effect proves that the native process executed the evolved
        # loop, rather than merely attaching its Snapshot ID to a seed run.
        with loop.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n_original_run = run\n"
                "async def run(*args, **kwargs):\n"
                "    result = await _original_run(*args, **kwargs)\n"
                "    result['answer'] = 'EVOLVED_LOOP:' + result['answer']\n"
                "    return result\n"
            )
        with (files / "skills/main.md").open("a", encoding="utf-8") as stream:
            stream.write("\nEVOLVED_SKILL_MARKER\n")
        evolved = seed.commit(files)
    source.update(evolved)
    snapshot_path = tmp_path / "appworld-selected.json"
    evolved.save(snapshot_path)
    original_bytes = snapshot_path.read_bytes()

    monkeypatch.setattr(appworld.shutil, "which", lambda _: "docker-fixture")
    monkeypatch.setattr(
        appworld, "_data_payload", lambda task, root: (root, root, set())
    )
    monkeypatch.setattr(
        appworld, "_docker", AsyncMock(return_value=SimpleNamespace(stdout="image-id"))
    )
    monkeypatch.setattr(appworld, "_cleanup", AsyncMock())
    staged = {}

    async def stop_before_docker_setup(docker, name, network, payload, config, timeout):
        staged["appworld"] = json.loads((payload / "request.json").read_text())
        staged["snapshot"] = Snapshot.load(payload / "snapshot.json")
        assert (payload / "appworld_client.py").is_file()
        raise RuntimeError("fixture: stop before starting a real container")

    monkeypatch.setattr(appworld, "_setup", stop_before_docker_setup)
    # Only package copying is omitted. Both bridges still serialize the real
    # Snapshot, prompt, config and dependency request.
    with monkeypatch.context() as patch:
        patch.setattr(_container_payload.shutil, "copytree", lambda *args, **kw: None)
        appworld.bind(source, {})
        source_result = asyncio.run(
            source.rollout(
                (Task("appworld-task", "Modify an application.", env="fixture"),)
            )
        )
    assert "fixture: stop before" in source_result[0].error_message
    assert "AppWorld tools are available" in staged["appworld"]["prompt"]
    assert staged["snapshot"].id == evolved.id
    assert source.snapshot.id == evolved.id
    assert not any("appworld_client" in name for name in evolved.files)

    root, _ = dataset
    config = load_config(
        overrides={
            "run": {"mode": "evaluate", "snapshot": str(snapshot_path)},
            "agent": {
                "name": "miniagent",
                "max_turns": 1,
                "llm": {
                    "model_name": "destination-model",
                    "api_key": "local-credential",
                    "base_url": local_model.url,
                },
            },
            "benchmark": {
                "name": "spreadsheetbench2",
                "category": "Template",
                "data_path": str(root),
                "split_counts": {"train": 0, "dev": 0, "test": 1},
            },
        }
    )
    from flashrsi import _startup

    monkeypatch.setattr(_startup, "_preflight", AsyncMock())
    target, benchmark = asyncio.run(runner._prepare_evaluation(config))
    assert target._env_runner is harbor._run
    assert source._env_runner is not target._env_runner
    assert target.snapshot.id == evolved.id
    task = benchmark.test[0]
    assert (
        Path(task.env) / "environment/input.xlsx"
    ).read_bytes() == b"PUBLIC_WORKBOOK"
    payload = tmp_path / "spreadsheet-payload"
    payload.mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(_container_payload.shutil, "copytree", lambda *args, **kw: None)
        harbor._stage(payload, target, target.config, task.question)
    assert not (payload / "appworld_client.py").exists()
    assert Snapshot.load(payload / "snapshot.json").files == evolved.files
    request = json.loads((payload / "request.json").read_text())
    assert "AppWorld" not in request["prompt"]
    assert "SpreadsheetBench2 task environment:" in request["prompt"]
    assert "/usr/local/bin/python" in request["prompt"]

    # Relocate the serialized container request to a local fixture directory;
    # the real container entry then launches the native MiniAgent subprocess.
    request["snapshot_path"] = str(payload / "snapshot.json")
    (payload / "request.json").write_text(json.dumps(request))
    task_dir = tmp_path / "spreadsheet-working"
    task_dir.mkdir()
    monkeypatch.chdir(task_dir)
    output = payload / "trajectory.json"
    assert asyncio.run(_container._run(payload / "request.json", output)) == 0
    result = json.loads(output.read_text())
    assert result["status"] == "finished", result["error_message"]
    assert result["output"] == "EVOLVED_LOOP:done"
    assert result["messages"][0]["snapshot_id"] == evolved.id
    assert len(local_model.requests) == 1
    model_input = json.dumps(local_model.requests[0])
    assert "EVOLVED_SKILL_MARKER" in model_input
    assert "SpreadsheetBench2 task environment:" in model_input
    assert "AppWorld tools" not in model_input
    assert "source-credential" not in model_input
    assert local_model.requests[0]["model"] == "destination-model"
    assert snapshot_path.read_bytes() == original_bytes
    assert source.snapshot.files == target.snapshot.files == evolved.files
