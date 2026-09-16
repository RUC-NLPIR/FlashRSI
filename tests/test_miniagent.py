"""MiniAgent integration tests use its real subprocess and SDK against localhost."""

import asyncio
import importlib.util
import inspect
import json
import os
import shutil
import signal
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from flashrsi.agents import MiniAgent
from flashrsi.benchmarks import SearchQA
from flashrsi.config import load_config
from flashrsi.core import Snapshot, Task

pytest.importorskip(
    "openai", reason="MiniAgent SDK integration needs the miniagent extra"
)


def _chat_reply(body, text="Paris", *, tool=None):
    message = {"role": "assistant", "content": text}
    if tool:
        name, arguments = tool
        message.update(
            content="",
            tool_calls=[
                {
                    "id": "call_edit",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        )
    return {
        "id": "chatcmpl_local",
        "object": "chat.completion",
        "created": 1,
        "model": body["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if tool else "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }


def _responses_reply(body, text="Paris"):
    return {
        "id": "resp_local",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "error": None,
        "model": body["model"],
        "output": [
            {
                "id": "msg_local",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 13,
            "output_tokens": 4,
            "total_tokens": 17,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 1},
        },
    }


@pytest.fixture
def model_server():
    """Provide valid provider responses without replacing SDK or runtime code."""

    class LocalModel:
        requests = []
        errors = []

        def reply(self, request):
            body = request["body"]
            if request["path"].endswith("/responses"):
                return 200, _responses_reply(body)
            return 200, _chat_reply(body)

    model = LocalModel()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                request = {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": json.loads(
                        self.rfile.read(int(self.headers["Content-Length"]))
                    ),
                }
                model.requests.append(request)
                status, response = model.reply(request)
            except Exception as error:
                model.errors.append(error)
                status, response = 500, {"error": {"message": "test server error"}}
            payload = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    model.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield model
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not model.errors


def _config(model_server, **overrides):
    return {
        "model_name": "custom-model",
        "api_key": "local-test-key",
        "base_url": model_server.base_url,
        **overrides,
    }


def _copy_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(inspect.getfile(MiniAgent)).parent,
        source,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return source


def _trace_text(trajectory):
    return json.dumps(
        {
            "output": trajectory.output,
            "error": trajectory.error_message,
            "messages": [dict(message) for message in trajectory.messages],
            "usage": dict(trajectory.usage),
        }
    )


@pytest.mark.parametrize("full_config", [False, True])
def test_text_run_uses_real_chat_sdk_with_defaults(model_server, full_config):
    config = _config(model_server)
    agent = MiniAgent({"agent": config} if full_config else config)
    trajectory = asyncio.run(agent.run("Capital of France?"))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Paris" and trajectory.task is None
    assert len(model_server.requests) == 1
    request = model_server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer local-test-key"
    assert request["body"]["max_tokens"] == 4096
    assert "reasoning_effort" not in request["body"]
    assert "thinking" not in request["body"]
    assert request["body"]["messages"][-1]["content"] == "Capital of France?"
    assert "Capital of France?" in _trace_text(trajectory)
    assert "Paris" in json.dumps([dict(item) for item in trajectory.messages])
    assert "prompt_tokens" in json.dumps(dict(trajectory.usage))
    assert trajectory.usage["model_calls"][0]["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 3,
        "total_tokens": 14,
    }
    assert all(
        "local-test-key" not in file.content.decode()
        for file in agent.snapshot.files.values()
    )


def test_openai_model_uses_real_responses_sdk(model_server):
    agent = MiniAgent(_config(model_server, model_name="openai/gpt-5"))
    trajectory = asyncio.run(agent.run("Capital of France?"))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "Paris"
    request = model_server.requests[0]
    assert request["path"] == "/v1/responses"
    assert request["body"]["model"] == "gpt-5"
    assert request["body"]["max_output_tokens"] == 4096
    assert request["body"]["store"] is False
    assert "reasoning" not in request["body"]
    assert "thinking" not in request["body"]
    assert "input_tokens" in json.dumps(dict(trajectory.usage))
    assert "reasoning_tokens" in json.dumps(dict(trajectory.usage))
    assert trajectory.messages[-1]["content"] == "Paris"


@pytest.mark.parametrize("model_name", ["organization/custom-model", "anthropic/model"])
def test_namespaced_model_ids_use_compatible_sdk_unchanged(model_server, model_name):
    result = asyncio.run(
        MiniAgent(_config(model_server, model_name=model_name)).run("question")
    )

    assert result.status == "finished", result.error_message
    request = model_server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["body"]["model"] == model_name
    assert request["authorization"] == "Bearer local-test-key"
    assert "thinking" not in request["body"]


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
@pytest.mark.parametrize("effort", [None, "", "none", "low"])
def test_reasoning_effort_is_explicit_and_not_inferred(
    model_server, model_name, effort
):
    result = asyncio.run(
        MiniAgent(
            _config(model_server, model_name=model_name, reasoning_effort=effort)
        ).run("question")
    )

    assert result.status == "finished", result.error_message
    body = model_server.requests[0]["body"]
    field = "reasoning" if model_name == "gpt-5" else "reasoning_effort"
    if effort:
        assert body[field] == ({"effort": effort} if model_name == "gpt-5" else effort)
    else:
        assert field not in body
    assert "thinking" not in body


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
def test_extra_body_reaches_the_selected_sdk_api(model_server, model_name):
    extra_body = {
        "thinking": {"type": "disabled"},
        "provider_options": {"tag": "explicit", "flags": [True, None, 3]},
    }
    config = load_config(
        overrides={
            "agent": _config(
                model_server, model_name=model_name, extra_body=extra_body
            ),
            "algorithm": {"worker": {"model_name": "other-model"}},
        }
    )
    result = asyncio.run(MiniAgent(config).run("question"))

    assert result.status == "finished", result.error_message
    request = model_server.requests[0]
    api = "responses" if model_name == "gpt-5" else "chat/completions"
    assert request["path"] == f"/v1/{api}"
    for key, value in extra_body.items():
        assert request["body"][key] == value
    assert "extra_body" not in request["body"]


def test_rollout_preserves_tasks_and_can_be_graded_locally(model_server, tmp_path):
    data = tmp_path / "questions.json"
    data.write_text(
        json.dumps(
            [
                {
                    "id": f"question-{index}",
                    "question": "Capital of France?",
                    "context": "Paris is the capital of France.",
                    "answers": ["Paris"],
                }
                for index in range(3)
            ]
        )
    )
    config = load_config(
        overrides={
            "benchmark": {"data_path": data},
            "agent": _config(model_server),
            "algorithm": {"worker": {"model_name": "custom-model"}},
        }
    )
    benchmark = SearchQA(config)
    benchmark.load()
    agent = MiniAgent(config)
    (trajectory,) = asyncio.run(agent.rollout(benchmark.dev))
    (graded,) = benchmark.grade((trajectory,))

    assert trajectory.task is benchmark.dev[0]
    assert trajectory.metrics == {}
    assert graded.metrics == {"exact_match": 1, "f1": 1}
    assert graded.messages == trajectory.messages
    assert graded.usage == trajectory.usage and trajectory.usage


def test_skill_candidate_changes_requests_without_selecting_it(model_server, tmp_path):
    source = _copy_source(tmp_path)
    (source / "skills/main.md").write_text("Answer marker: baseline.")

    def reply(request):
        system = request["body"]["messages"][0]["content"]
        answer = "candidate" if "Answer marker: candidate." in system else "baseline"
        return 200, _chat_reply(request["body"], answer)

    model_server.reply = reply
    agent = MiniAgent(_config(model_server, source_dir=source))
    agent.set_scope({"skill": "rw"})
    baseline = agent.snapshot
    with baseline.check_out() as directory:
        (directory / "skills/main.md").write_text("Answer marker: candidate.")
        candidate = baseline.commit(directory)
    saved = tmp_path / "candidate.json"
    candidate.save(saved)

    (trial,) = asyncio.run(
        agent.rollout([Task("trial", "question")], snapshot=Snapshot.load(saved))
    )
    assert trial.output == "candidate"
    assert agent.snapshot is baseline
    assert asyncio.run(agent.run("question")).output == "baseline"
    agent.update(candidate)
    assert asyncio.run(agent.run("question")).output == "candidate"
    assert (source / "skills/main.md").read_text() == "Answer marker: baseline."


def test_code_candidate_is_executed_from_its_snapshot(model_server, tmp_path):
    agent = MiniAgent(_config(model_server))
    agent.set_scope({"code": "rw"})
    baseline = agent.snapshot
    marker = tmp_path / "executed.json"
    with baseline.check_out() as directory:
        script = directory / "runtime/agent.py"
        script.write_text(
            script.read_text()
            + "\nfrom pathlib import Path as _TestPath\n"
            + "import json as _test_json\n"
            + "import os as _test_os\n"
            + f"_TestPath({str(marker)!r}).write_text(_test_json.dumps({{"
            + "'pid': _test_os.getpid(), 'root': str(_TestPath(__file__).resolve().parents[1])}))\n"
        )
        candidate = baseline.commit(directory)

    assert asyncio.run(agent.run("question")).output == "Paris"
    assert not marker.exists()
    (trajectory,) = asyncio.run(
        agent.rollout([Task("candidate", "question")], snapshot=candidate)
    )
    assert trajectory.status == "finished", trajectory.error_message
    executed = json.loads(marker.read_text())
    assert executed["pid"] != os.getpid()
    assert not Path(executed["root"]).exists()
    assert agent.snapshot is baseline


@pytest.mark.parametrize("model_name", ["custom-model", "openai/gpt-5"])
def test_worker_edits_target_with_its_own_skill_configuration(
    model_server, tmp_path, model_name
):
    source = _copy_source(tmp_path)
    (source / "skills/main.md").write_text("WORKER_PRIVATE_INSTRUCTIONS")
    target = tmp_path / "target"
    (target / "skills").mkdir(parents=True)
    (target / "skills/main.md").write_text("TARGET_UNRELATED_INSTRUCTIONS")
    (target / "agent.yaml").write_text("invalid: [target configuration must not load")

    def reply(request):
        body = request["body"]
        responses = request["path"].endswith("/responses")
        system = body["instructions"] if responses else body["messages"][0]["content"]
        assert "WORKER_PRIVATE_INSTRUCTIONS" in system
        assert "TARGET_UNRELATED_INSTRUCTIONS" not in system
        tools = body["tools"]
        names = [
            tool["name"] if responses else tool["function"]["name"] for tool in tools
        ]
        assert "write_file" in names
        edited = (target / "skills/main.md").read_text() == "updated skill"
        if responses:
            response = _responses_reply(body, "edited")
            if not edited:
                response["output"] = [
                    {
                        "type": "reasoning",
                        "id": "rs_local",
                        "summary": [],
                        "encrypted_content": "opaque-reasoning-state",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_local",
                        "call_id": "call_edit",
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "skills/main.md", "content": "updated skill"}
                        ),
                        "status": "completed",
                    },
                ]
            return 200, response
        tool = (
            None
            if edited
            else ("write_file", {"path": "skills/main.md", "content": "updated skill"})
        )
        response = _chat_reply(body, "edited", tool=tool)
        if tool:
            response["choices"][0]["message"]["reasoning_content"] = (
                "Choose the file tool."
            )
        return 200, response

    model_server.reply = reply
    worker = MiniAgent(_config(model_server, model_name=model_name, source_dir=source))
    baseline = worker.snapshot
    trajectory = asyncio.run(worker.run("Improve skills/main.md", working_dir=target))

    assert trajectory.status == "finished", trajectory.error_message
    assert trajectory.output == "edited"
    assert len(model_server.requests) == 2
    assert (target / "skills/main.md").read_text() == "updated skill"
    assert worker.snapshot is baseline
    assert (source / "skills/main.md").read_text() == "WORKER_PRIVATE_INSTRUCTIONS"
    assert "write_file" in _trace_text(trajectory)
    assert "updated skill" in _trace_text(trajectory)
    if model_name == "openai/gpt-5":
        first_assistant = next(
            message for message in trajectory.messages if message["role"] == "assistant"
        )
        call = first_assistant["tool_calls"][0]
        assert call["function"]["name"] == "write_file"
        assert any(
            item.get("call_id") == call["id"] and item.get("type") == "function_call"
            for item in model_server.requests[1]["body"]["input"]
        )
        assert any(
            item.get("type") == "reasoning"
            and item.get("encrypted_content") == "opaque-reasoning-state"
            for item in model_server.requests[1]["body"]["input"]
        )
    else:
        assistant = next(
            message
            for message in model_server.requests[1]["body"]["messages"]
            if message["role"] == "assistant"
        )
        assert assistant["reasoning_content"] == "Choose the file tool."


def test_api_error_returns_redacted_trace_without_retries(model_server):
    secret = "secret-key-that-must-not-appear"
    model_server.reply = lambda request: (
        401,
        {
            "error": {
                "message": f"Invalid credential {secret}",
                "type": "authentication_error",
            }
        },
    )
    agent = MiniAgent(_config(model_server, api_key=secret))
    trajectory = asyncio.run(agent.run("question"))

    assert trajectory.status == "error"
    assert trajectory.error_message
    assert len(model_server.requests) == 1
    assert secret not in _trace_text(trajectory)


def test_concurrent_instances_keep_endpoint_auth_and_options_isolated(
    model_server, monkeypatch
):
    inherited = {
        "FLASHRSI_MINIAGENT_API_KEY": "parent-key",
        "FLASHRSI_MINIAGENT_MODEL": "parent-model",
        "FLASHRSI_MINIAGENT_SIDE_MODEL": "parent-side-model",
        "FLASHRSI_MINIAGENT_BASE_URL": model_server.base_url + "/parent",
        "FLASHRSI_MINIAGENT_SIDE_BASE_URL": model_server.base_url + "/parent-side",
        "FLASHRSI_MINIAGENT_MAX_TOKENS": "not-an-integer",
        "FLASHRSI_MINIAGENT_LLM_MAX_RETRIES": "not-an-integer",
        "FLASHRSI_MINIAGENT_REASONING": "parent-effort",
        "FLASHRSI_MINIAGENT_EXTRA_BODY": "invalid inherited JSON",
    }
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    model_server.reply = lambda request: (
        200,
        _chat_reply(request["body"], request["body"]["model"]),
    )
    first = MiniAgent(
        _config(
            model_server,
            model_name="custom-model",
            base_url=model_server.base_url + "/first",
            api_key="first-key",
            max_tokens=31,
            reasoning_effort="low",
            extra_body={"provider_options": {"tag": "first"}},
        )
    )
    second = MiniAgent(
        _config(
            model_server,
            model_name="other-model",
            base_url=model_server.base_url + "/second",
            api_key="second-key",
            max_tokens=47,
            reasoning_effort="high",
            extra_body={"provider_options": {"tag": "second"}},
        )
    )

    async def scenario():
        return await asyncio.gather(
            first.run("first question"), second.run("second question")
        )

    trajectories = asyncio.run(scenario())
    assert [item.output for item in trajectories] == [
        "custom-model",
        "other-model",
    ]
    assert len(model_server.requests) == 2
    by_model = {request["body"]["model"]: request for request in model_server.requests}
    for model, label, max_tokens, effort in (
        ("custom-model", "first", 31, "low"),
        ("other-model", "second", 47, "high"),
    ):
        request = by_model[model]
        assert request["path"] == f"/v1/{label}/chat/completions"
        assert request["authorization"] == f"Bearer {label}-key"
        assert request["body"]["max_tokens"] == max_tokens
        assert request["body"]["reasoning_effort"] == effort
        assert request["body"]["provider_options"] == {"tag": label}
    assert {name: os.environ[name] for name in inherited} == inherited


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_name", None),
        ("model_name", ""),
        ("model_name", 12),
        ("api_key", 12),
        ("base_url", 12),
    ],
)
def test_public_model_fields_are_validated_by_config(field, value):
    with pytest.raises(ValueError, match=field):
        load_config(
            overrides={
                "agent": {"model_name": "custom-model", field: value},
                "algorithm": {"worker": {"model_name": "gpt-5"}},
            }
        )


def test_custom_model_uses_sdk_environment_defaults(model_server, monkeypatch):
    monkeypatch.setenv("FLASHRSI_MINIAGENT_BASE_URL", "https://legacy.invalid")
    monkeypatch.setenv("FLASHRSI_MINIAGENT_API_KEY", "unused-legacy-key")
    monkeypatch.setenv("FLASHRSI_MINIAGENT_MAX_TOKENS", "invalid-legacy-budget")
    monkeypatch.setenv("FLASHRSI_MINIAGENT_REASONING", "unused-legacy-effort")
    monkeypatch.setenv("FLASHRSI_MINIAGENT_EXTRA_BODY", "invalid inherited JSON")
    monkeypatch.setenv("OPENAI_BASE_URL", model_server.base_url)
    monkeypatch.setenv("OPENAI_API_KEY", "environment-test-key")
    agent = MiniAgent({"model_name": "custom-model"})
    result = asyncio.run(agent.run("question"))
    assert result.status == "finished", result.error_message
    request = model_server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["body"]["model"] == "custom-model"
    assert request["authorization"] == "Bearer environment-test-key"

    assert request["body"]["max_tokens"] == 4096
    assert "reasoning_effort" not in request["body"]
    assert "thinking" not in request["body"]


def test_deepseek_name_uses_generic_environment_without_provider_defaults(
    model_server, monkeypatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unused-provider-key")
    monkeypatch.setenv("OPENAI_API_KEY", "generic-environment-key")
    monkeypatch.setenv("OPENAI_BASE_URL", model_server.base_url)
    result = asyncio.run(MiniAgent({"model_name": "deepseek-v4-flash"}).run("question"))

    assert result.status == "finished", result.error_message
    request = model_server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["body"]["model"] == "deepseek-v4-flash"
    assert request["authorization"] == "Bearer generic-environment-key"
    assert "thinking" not in request["body"]
    assert "reasoning_effort" not in request["body"]
    assert os.environ["DEEPSEEK_API_KEY"] == "unused-provider-key"


def test_changed_config_is_used_on_the_next_run(model_server):
    agent = MiniAgent(_config(model_server))
    asyncio.run(agent.run("first"))
    agent.config.update(model_name="other-model", api_key="updated-key", max_tokens=73)
    result = asyncio.run(agent.run("second"))
    assert result.status == "finished", result.error_message
    assert model_server.requests[-1]["body"]["model"] == "other-model"
    assert model_server.requests[-1]["body"]["max_tokens"] == 73
    assert model_server.requests[-1]["authorization"] == "Bearer updated-key"


@pytest.mark.parametrize("side_model", [None, "gpt-5"])
def test_native_responses_keeps_main_endpoint_with_same_side_model(
    model_server, monkeypatch, side_model
):
    for name in os.environ:
        if name.startswith("FLASHRSI_MINIAGENT_"):
            monkeypatch.delenv(name)
    settings = {
        "FLASHRSI_MINIAGENT_API_KEY": "native-test-key",
        "FLASHRSI_MINIAGENT_MODEL": "gpt-5",
        "FLASHRSI_MINIAGENT_BASE_URL": model_server.base_url + "/main",
        "FLASHRSI_MINIAGENT_SIDE_BASE_URL": model_server.base_url + "/side",
    }
    if side_model is not None:
        settings["FLASHRSI_MINIAGENT_SIDE_MODEL"] = side_model
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    path = Path(inspect.getfile(MiniAgent)).parent / "runtime/llm.py"
    spec = importlib.util.spec_from_file_location("native_routing_llm", path)
    llm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(llm)

    async def scenario():
        try:
            await llm.responses("main question", model=llm.DEFAULT_MODEL)
            await llm.chat(
                [{"role": "user", "content": "side question"}],
                model=llm.SIDE_MODEL,
            )
        finally:
            for client in llm._clients.values():
                await client.close()

    asyncio.run(scenario())

    assert [request["path"] for request in model_server.requests] == [
        "/v1/main/responses",
        "/v1/side/chat/completions",
    ]
    for request in model_server.requests:
        assert request["body"]["model"] == "gpt-5"
        assert request["authorization"] == "Bearer native-test-key"


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
def test_middleware_side_call_uses_child_environment(
    model_server, tmp_path, monkeypatch, model_name
):
    source = _copy_source(tmp_path)
    (source / "agent.yaml").write_text(
        (source / "agent.yaml")
        .read_text()
        .replace("middlewares: []", "middlewares: [check]")
    )
    (source / "middleware").mkdir()
    (source / "middleware/check.py").write_text(
        "async def before_final(answer, ctx):\n"
        "    result = await ctx.side_text('check answer', purpose='review', max_tokens=23)\n"
        "    return {'action': 'replace', 'answer': result or 'side call failed'}\n"
    )
    monkeypatch.setenv("FLASHRSI_MINIAGENT_SIDE_MODEL", "unused-legacy-model")
    monkeypatch.setenv("FLASHRSI_MINIAGENT_SIDE_BASE_URL", "https://legacy.invalid")

    def reply(request):
        answer = "checked" if len(model_server.requests) == 2 else "draft"
        response = (
            _responses_reply(request["body"], answer)
            if request["path"].endswith("/responses")
            else _chat_reply(request["body"], answer)
        )
        return 200, response

    model_server.reply = reply
    agent = MiniAgent(
        _config(
            model_server,
            model_name=model_name,
            source_dir=source,
            reasoning_effort="low",
            extra_body={"provider_options": {"tag": "side-and-main"}},
        )
    )
    result = asyncio.run(agent.run("question"))
    assert result.status == "finished", result.error_message
    assert result.output == "checked"
    assert len(model_server.requests) == 2
    for request in model_server.requests:
        assert request["body"]["provider_options"] == {"tag": "side-and-main"}
    request = model_server.requests[-1]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer local-test-key"
    assert request["body"]["model"] == model_name
    token_field = "max_completion_tokens" if model_name == "gpt-5" else "max_tokens"
    assert request["body"][token_field] == 23
    assert request["body"]["reasoning_effort"] == "low"
    assert result.usage["model_calls"][-1]["role"] == "side"


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
def test_forced_answer_uses_current_model_and_budget(
    model_server, tmp_path, model_name
):
    def reply(request):
        body = request["body"]
        if request["path"].endswith("/responses"):
            response = _responses_reply(body, "final answer")
            if len(model_server.requests) == 1:
                response["output"] = [
                    {
                        "type": "function_call",
                        "id": "fc_forced",
                        "call_id": "call_edit",
                        "name": "list_files",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ]
        else:
            tool = ("list_files", {}) if len(model_server.requests) == 1 else None
            response = _chat_reply(body, "final answer", tool=tool)
        return 200, response

    model_server.reply = reply
    agent = MiniAgent(
        _config(model_server, model_name=model_name, max_turns=1, max_tokens=97)
    )
    result = asyncio.run(agent.run("question", working_dir=tmp_path))
    assert result.status == "finished", result.error_message
    assert result.output == "final answer"
    assert len(model_server.requests) == 2
    for request in model_server.requests:
        assert request["authorization"] == "Bearer local-test-key"
        field = "max_output_tokens" if model_name == "gpt-5" else "max_tokens"
        assert request["body"][field] == 97
    assert result.usage["model_calls"][-1]["role"] == "forced_answer"


@pytest.mark.parametrize("model_name", ["custom-model", "gpt-5"])
def test_incomplete_response_is_error_and_keeps_partial_trace(model_server, model_name):
    def reply(request):
        if request["path"].endswith("/responses"):
            response = _responses_reply(request["body"], "unfinished answer")
            response.update(
                status="incomplete", incomplete_details={"reason": "max_output_tokens"}
            )
        else:
            response = _chat_reply(request["body"], "unfinished answer")
            response["choices"][0]["finish_reason"] = "length"
        return 200, response

    model_server.reply = reply
    result = asyncio.run(
        MiniAgent(_config(model_server, model_name=model_name)).run("q")
    )
    assert result.status == "error"
    assert result.output == ""
    assert "budget" in result.error_message.lower()
    assert result.usage["model_calls"][0]["usage"]["total_tokens"] > 0
    assert "unfinished answer" in _trace_text(result)
    assert len(model_server.requests) == 1


def test_server_errors_obey_native_retry_limit(model_server):
    model_server.reply = lambda request: (500, {"error": {"message": "unavailable"}})
    result = asyncio.run(MiniAgent(_config(model_server, llm_max_retries=1)).run("q"))
    assert result.status == "error"
    assert "500" in result.error_message
    assert len(model_server.requests) == 1


def test_timeout_reports_error_and_leaves_completed_edits(model_server, tmp_path):
    release = threading.Event()

    def reply(request):
        if len(model_server.requests) == 1:
            return 200, _chat_reply(
                request["body"],
                tool=("write_file", {"path": "notes.txt", "content": "saved"}),
            )
        release.wait(timeout=10)
        return 200, _chat_reply(request["body"], "late answer")

    model_server.reply = reply
    agent = MiniAgent(_config(model_server, timeout=3))
    try:
        result = asyncio.run(agent.run("Write notes.txt", working_dir=tmp_path))
    finally:
        release.set()
    assert result.status == "error" and "timed out" in result.error_message
    assert len(model_server.requests) == 2
    assert (tmp_path / "notes.txt").read_text() == "saved"
    assert result.messages == ()
    assert result.usage == {}


@pytest.mark.parametrize("include_messages", [True, False])
def test_adapter_only_needs_native_result_not_log_files(tmp_path, include_messages):
    source = _copy_source(tmp_path)
    (source / "runtime/agent.py").write_text(
        "import os, subprocess, sys\n"
        "async def run(question, *, model, max_turns, workspace_dir, runs_root):\n"
        "    print('native console log without newline', end='')\n"
        "    os.write(1, b'raw native output\\n')\n"
        "    subprocess.run([sys.executable, '-c', 'print(123)'], check=True)\n"
        "    result = {'answer': question, 'stop_reason': 'completed', 'usage': [], 'turns': 1}\n"
        + (
            "    result['messages'] = [{'role': 'assistant', 'content': os.environ['FLASHRSI_MINIAGENT_API_KEY']}]\n"
            if include_messages
            else ""
        )
        + "    return result\n"
    )
    agent = MiniAgent(
        {
            "model_name": "unused",
            "source_dir": source,
            "api_key": 'quoted"key\\with\nnewline',
        }
    )
    result = asyncio.run(agent.run("native answer"))
    assert result.status == "finished", result.error_message
    assert result.output == "native answer"
    assert result.messages == (
        ({"role": "assistant", "content": "[REDACTED]"},) if include_messages else ()
    )
    assert result.usage == {"model_calls": [], "turns": 1}


def test_disabled_builtin_tool_cannot_be_called(model_server, tmp_path):
    source = _copy_source(tmp_path)
    marker = tmp_path / "web-tool-called"
    # An enabled built-in would execute this implementation. No web call occurs.
    (source / "runtime/tools.py").write_text(
        "from pathlib import Path\n"
        "async def web_search_structured(query):\n"
        f"    Path({str(marker)!r}).write_text(query)\n"
        "    return 'unexpected', []\n"
        "async def web_fetch(url):\n"
        "    return ''\n"
    )

    def reply(request):
        if len(model_server.requests) == 1:
            return 200, _chat_reply(
                request["body"], tool=("web_search", {"query": "not enabled"})
            )
        return 200, _chat_reply(request["body"], "Paris")

    model_server.reply = reply
    result = asyncio.run(MiniAgent(_config(model_server, source_dir=source)).run("q"))
    assert result.status == "finished", result.error_message
    assert not marker.exists()
    assert "Unavailable tool: web_search" in _trace_text(result)


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_timeout_and_cancellation_stop_child_and_remove_export(tmp_path, mode):
    source = _copy_source(tmp_path)
    started = tmp_path / "started.json"
    continued = tmp_path / "continued"
    (source / "runtime/agent.py").write_text(
        "import json, os, time\n"
        "from pathlib import Path\n"
        f"Path({str(started)!r}).write_text(json.dumps({{"
        "'pid': os.getpid(), 'root': str(Path(__file__).resolve().parents[1])}))\n"
        "time.sleep(30)\n"
        f"Path({str(continued)!r}).write_text('child was not stopped')\n"
    )
    agent = MiniAgent(
        {
            "model_name": "custom-model",
            "source_dir": source,
            "timeout": 0.5 if mode == "timeout" else 30,
        }
    )

    async def scenario():
        running = asyncio.create_task(agent.run("question"))
        try:
            if mode == "timeout":
                trajectory = await asyncio.wait_for(running, 5)
                assert trajectory.status == "error"
                assert (
                    "timeout" in trajectory.error_message.lower()
                    or "timed out" in trajectory.error_message.lower()
                )
            else:
                async with asyncio.timeout(5):
                    while not started.exists():
                        await asyncio.sleep(0.01)
                running.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await running
        finally:
            if not running.done():
                running.cancel()
                with suppress(asyncio.CancelledError):
                    await running

    try:
        asyncio.run(scenario())
        recorded = json.loads(started.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(recorded["pid"], 0)
        assert not Path(recorded["root"]).exists()
        assert not continued.exists()
        with pytest.raises(RuntimeError, match="only inside"):
            agent.files_dir
    finally:
        if started.exists():
            with suppress(ProcessLookupError):
                os.kill(json.loads(started.read_text())["pid"], signal.SIGKILL)
