"""Pinned upstream compaction oracles and real native-loop integration tests.

The checked-in oracle runs Pi's original TypeScript with fixed, offline model
replies. The tests need Python only and never contact a model endpoint.
"""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from flashrsi.agents.pi_agent.runtime.pi_native import loop
from flashrsi.agents.pi_agent.runtime.pi_native.compaction import (
    DEFAULT_SETTINGS,
    SUMMARIZATION_SYSTEM_PROMPT,
    content_text,
    estimate_context_tokens,
    estimate_tokens,
    is_context_overflow,
    is_recoverable_length,
    model_limits,
    prepare_compaction,
    serialize_conversation,
    settings,
    should_compact,
)
from flashrsi.agents.pi_agent.runtime.pi_native.openai_provider import sanitize
from flashrsi.agents.pi_agent.runtime.pi_native.resources import ResourceBundle
from flashrsi.agents.pi_agent.runtime.pi_native.session import Session

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "pi_compaction_upstream.json").read_text()
)
HISTORY = ORACLE["cases"][0]["input"]["entries"]
ZERO = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0}


def seed(tmp_path, entries=None):
    path = tmp_path / "session.jsonl"
    header = {
        "type": "session",
        "version": 3,
        "id": "offline-session",
        "timestamp": "2026-10-31T00:00:00.000Z",
        "cwd": str(tmp_path),
    }
    path.write_text(
        "\n".join(
            json.dumps(v)
            for v in [header, *(entries if entries is not None else HISTORY)]
        )
        + "\n"
    )
    return path


def config(session_file=None, **updates):
    result = {
        "llm": {
            "model_name": "openai/oracle",
            "api_key": "fixture-only",
            "base_url": "https://offline.invalid/v1",
            "max_retries": 0,
        },
        "context_window": 128000,
        "model_max_tokens": 4096,
        "tools": [],
        "compaction": {"keepRecentTokens": 11},
        "max_turns": 5,
    }
    if session_file:
        result["session_file"] = str(session_file)
    result.update(updates)
    return result


def completion(text="done", *, reason="stop", calls=None, usage=None):
    message = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"]),
                },
            }
            for call in calls
        ]
    return httpx.Response(
        200,
        json={
            "choices": [{"message": message, "finish_reason": reason}],
            "usage": usage or ZERO,
        },
    )


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        loop.httpx,
        "AsyncClient",
        lambda *args, **kwargs: original(
            *args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False
        ),
    )


def run(tmp_path, cfg, prompt="follow-up", **kwargs):
    return asyncio.run(
        loop.run(
            cfg,
            prompt,
            tmp_path,
            tmp_path,
            ResourceBundle(system_prompt="system", tool_schemas=[]),
            **kwargs,
        )
    )


@pytest.mark.parametrize("case", ORACLE["tokens"])
def test_pi_compaction_estimator_matches_actual_upstream(case):
    assert estimate_tokens(case["message"]) == case["expected"]


def test_pi_compaction_context_and_serialization_match_actual_upstream():
    case = ORACLE["context"]
    assert estimate_context_tokens(case["messages"]) == case["expected"]
    case = ORACLE["serialization"]
    assert serialize_conversation(case["messages"]) == case["expected"]


@pytest.mark.parametrize("case", ORACLE["overflow"])
def test_pi_overflow_detection_matches_actual_upstream(case):
    source = case["input"]
    assert is_context_overflow(source["message"], source["window"]) == case["overflow"]
    assert is_recoverable_length(source["message"], 4096) == case["recoverable"]


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda c: c["input"]["name"])
def test_pi_native_manual_compaction_replays_upstream_requests_and_checkpoint(
    case, tmp_path, monkeypatch
):
    source, expected = case["input"], case["expected"]
    entries = copy.deepcopy(source["entries"])
    options = {**DEFAULT_SETTINGS, "keepRecentTokens": source["keep"]}
    assert prepare_compaction(entries, options) == expected["preparation"]
    path = seed(tmp_path, entries)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT
        return completion(f"summary-{len(requests)}")

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path, compaction=options), "/compact preserve paths")
    if expected["result"] is None:
        assert result.status == "error"
        assert requests == []
        assert Session(tmp_path, path).entries == entries
        return
    assert result.status == "finished"
    actual = next(e["result"] for e in result.events if e["type"] == "compaction_end")
    assert {key: actual[key] for key in expected["result"]} == expected["result"]
    assert len(requests) == len(expected["requests"])
    for actual_request, original_request in zip(
        requests, expected["requests"], strict=True
    ):
        original_messages = original_request["messages"]
        assert (
            actual_request["messages"][0]["content"] == original_messages[0]["content"]
        )
        assert actual_request["messages"][1]["content"] == sanitize(
            content_text(original_messages[1]["content"])
        )
        assert (
            actual_request["max_completion_tokens"] == 4096
        )  # model output limit, independent of reserveTokens
        assert "tools" not in actual_request
    session = Session(tmp_path, path)
    assert session.entries[-1]["type"] == "compaction"
    system = {
        key: value
        for key, value in session.entries[-1]["systemMessage"].items()
        if key != "timestamp"
    }
    assert system == expected["systemAfter"]
    assert (
        session.entries[: len(entries)] == entries
    )  # raw transcript is never destroyed
    assert any(m["role"] == "compactionSummary" for m in session.messages())
    assert not any(
        "old request" in content_text(m.get("content", [])) for m in session.messages()
    )


def test_pi_compaction_settings_threshold_and_model_override(tmp_path):
    directory = tmp_path / ".pi" / "agent"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(
        json.dumps(
            {
                "compaction": {
                    "reserveTokens": 20,
                    "keepRecentTokens": 10,
                    "modelOverrides": {"openai/oracle": {"keepRecentTokens": 3}},
                }
            }
        )
    )
    value = settings(config(), tmp_path)
    assert value["reserveTokens"] == 20
    assert value["keepRecentTokens"] == 11  # explicit role config wins
    assert should_compact(81, 100, value)
    assert not should_compact(80, 100, value)
    assert not should_compact(100, 100, {**value, "enabled": False})


def test_pi_threshold_compacts_before_prompt_and_restores_summary_on_resume(
    tmp_path, monkeypatch
):
    entries = copy.deepcopy(HISTORY)
    entries[-1]["message"]["usage"] = {**ZERO, "input": 95, "totalTokens": 95}
    path = seed(tmp_path, entries)
    conversation_requests = []
    summaries = []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("durable checkpoint")
        conversation_requests.append(payload)
        return completion("completed", usage={**ZERO, "input": 5, "totalTokens": 5})

    transport(monkeypatch, handler)
    cfg = config(
        path,
        context_window=100,
        compaction={"reserveTokens": 10, "keepRecentTokens": 11},
    )
    result = run(tmp_path, cfg)
    assert result.status == "finished"
    assert len(summaries) == 1
    assert len(conversation_requests) == 1
    assert result.events[1]["type"] == "compaction_start"
    sent = json.dumps(conversation_requests[0]["messages"])
    assert "durable checkpoint" in sent
    assert "old request" not in sent
    assert "current task" in sent
    assert "follow-up" in sent
    # A fresh runtime process must replay the checkpoint rather than old raw messages.
    resumed = run(tmp_path, {**cfg, "compaction": {"enabled": False}}, "second prompt")
    assert resumed.status == "finished"
    assert len(summaries) == 1
    assert "durable checkpoint" in json.dumps(conversation_requests[-1]["messages"])


@pytest.mark.parametrize("second_error", [False, True])
def test_pi_context_overflow_compacts_and_retries_exactly_once(
    tmp_path, monkeypatch, second_error
):
    path = seed(tmp_path)
    requests, summaries = [], []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("overflow checkpoint")
        requests.append(payload)
        if len(requests) == 1 or second_error:
            return httpx.Response(
                400,
                json={"error": {"message": "context_length_exceeded: input too large"}},
            )
        return completion("recovered", usage={**ZERO, "input": 5, "totalTokens": 5})

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path))
    assert result.status == ("error" if second_error else "finished")
    assert len(requests) == 2
    assert len(summaries) in {1, 2}  # history + optional split-turn prefix
    assert "overflow checkpoint" in json.dumps(requests[-1]["messages"])
    assert sum(e["type"] == "agent_start" for e in result.events) == 2
    assert sum(e["type"] == "agent_settled" for e in result.events) == 1
    session = Session(tmp_path, path)
    assert sum(e["type"] == "context_edit" for e in session.entries) == 1
    if second_error:
        errors = [
            e
            for e in result.events
            if e["type"] == "compaction_end" and e.get("errorMessage")
        ]
        assert "after one compact-and-retry attempt" in errors[-1]["errorMessage"]


@pytest.mark.parametrize("failure", ["length", "error", "tool_calls", "aborted"])
def test_pi_failed_summary_preserves_full_session_and_does_not_continue(
    tmp_path, monkeypatch, failure
):
    path = seed(tmp_path)
    before = path.read_bytes()

    def handler(request):
        if failure == "tool_calls":
            return completion(
                "bad",
                reason="tool_calls",
                calls=[
                    {
                        "id": "oops",
                        "name": "write",
                        "arguments": {"path": "no", "content": "bad"},
                    }
                ],
            )
        return completion("partial summary", reason=failure)

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path), "/compact")
    assert result.status == "error"
    assert path.read_bytes() == before
    assert not (tmp_path / "no").exists()
    assert not any(e["type"] == "agent_start" for e in result.events)


def test_pi_compaction_cancel_preserves_full_session(tmp_path, monkeypatch):
    path = seed(tmp_path)
    before = path.read_bytes()

    async def scenario():
        cancel = asyncio.Event()

        async def handler(request):
            cancel.set()
            await asyncio.Event().wait()

        transport(monkeypatch, handler)
        result = await loop.run(
            config(path),
            "/compact",
            tmp_path,
            tmp_path,
            ResourceBundle(system_prompt="system", tool_schemas=[]),
            cancel_compaction=cancel,
        )
        assert result.status == "error"
        assert result.events[-1]["aborted"] is True

    asyncio.run(scenario())
    assert path.read_bytes() == before


def test_pi_overflow_summary_failure_keeps_original_attempt(tmp_path, monkeypatch):
    path = seed(tmp_path)

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            return completion("partial", reason="length")
        return httpx.Response(400, json={"error": {"message": "prompt is too long"}})

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path))
    assert result.status == "error"
    session = Session(tmp_path, path)
    assert not any(e["type"] in {"compaction", "context_edit"} for e in session.entries)
    assert any(
        m.get("errorMessage") and "prompt is too long" in m["errorMessage"]
        for m in session.messages()
    )


def test_pi_prior_length_overflow_is_compacted_before_new_prompt_without_old_turn_retry(
    tmp_path, monkeypatch
):
    entries = copy.deepcopy(HISTORY)
    entries[-1]["message"].update(
        stopReason="length",
        usage={**ZERO, "input": 100, "output": 0, "totalTokens": 100},
    )
    path = seed(tmp_path, entries)
    requests, summaries = [], []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("prior overflow checkpoint")
        requests.append(payload)
        return completion(
            "new prompt done", usage={**ZERO, "input": 5, "totalTokens": 5}
        )

    transport(monkeypatch, handler)
    result = run(
        tmp_path,
        config(
            path,
            context_window=100,
            compaction={"reserveTokens": 0, "keepRecentTokens": 1},
        ),
        "new prompt",
    )
    assert result.status == "finished"
    assert len(requests) == 1
    assert summaries
    assert requests[0]["messages"][-1] == {"role": "user", "content": "new prompt"}
    end = next(e for e in result.events if e["type"] == "compaction_end")
    assert end["reason"] == "overflow"
    assert end["willRetry"] is True


def test_pi_post_response_threshold_compaction_keeps_completed_answer(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    requests, summaries = [], []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("post-response checkpoint")
        requests.append(payload)
        return completion(
            "completed answer", usage={**ZERO, "input": 95, "totalTokens": 95}
        )

    transport(monkeypatch, handler)
    result = run(
        tmp_path,
        config(
            path,
            context_window=100,
            compaction={"reserveTokens": 10, "keepRecentTokens": 5},
        ),
    )
    assert result.status == "finished"
    assert result.output == "completed answer"
    assert len(requests) == 1
    assert summaries
    types = [e["type"] for e in result.events]
    assert (
        types.index("agent_end")
        < types.index("compaction_start")
        < types.index("agent_settled")
    )


def test_pi_threshold_compaction_between_tool_turns_preserves_tool_pair(
    tmp_path, monkeypatch
):
    from flashrsi.agents.pi_agent.runtime.pi_native.tools import tool_schemas

    path = seed(tmp_path)
    requests, summaries = [], []
    call = {
        "id": "write-1",
        "name": "write",
        "arguments": {"path": "written.txt", "content": "tool result"},
    }

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("tool-turn checkpoint")
        requests.append(payload)
        if len(requests) == 1:
            return completion(
                "",
                reason="tool_calls",
                calls=[call],
                usage={**ZERO, "input": 995, "totalTokens": 995},
            )
        return completion(
            "completed tool task", usage={**ZERO, "input": 5, "totalTokens": 5}
        )

    transport(monkeypatch, handler)
    result = asyncio.run(
        loop.run(
            config(
                path,
                tools=["write"],
                context_window=1000,
                compaction={"reserveTokens": 10, "keepRecentTokens": 5},
            ),
            "write a file",
            tmp_path,
            tmp_path,
            ResourceBundle(
                system_prompt="system", tool_schemas=tool_schemas(["write"])
            ),
        )
    )
    assert result.status == "finished"
    assert (tmp_path / "written.txt").read_text() == "tool result"
    assert len(requests) == 2
    assert summaries
    sent = requests[-1]["messages"]
    tool_index = next(i for i, m in enumerate(sent) if m["role"] == "tool")
    assert (
        sent[tool_index - 1]["tool_calls"][0]["id"] == sent[tool_index]["tool_call_id"]
    )
    assert "tool-turn checkpoint" in json.dumps(sent)


def test_pi_summary_transient_failures_use_snapshot_retry_policy(tmp_path, monkeypatch):
    path = seed(tmp_path)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(
                503, json={"error": {"message": "temporarily unavailable"}}
            )
        return completion("retried checkpoint")

    transport(monkeypatch, handler)
    result = run(
        tmp_path,
        config(path, retry={"enabled": True, "maxRetries": 1, "baseDelayMs": 0}),
        "/compact",
    )
    assert result.status == "finished"
    assert len(requests) == 2
    assert [
        e["type"] for e in result.events if e["type"].startswith("summarization_retry")
    ] == [
        "summarization_retry_scheduled",
        "summarization_retry_attempt_start",
        "summarization_retry_finished",
    ]


def test_pi_summary_billing_failure_is_not_retried(tmp_path, monkeypatch):
    path = seed(tmp_path)
    before = path.read_bytes()
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(
            429, json={"error": {"message": "insufficient_quota billing"}}
        )

    transport(monkeypatch, handler)
    result = run(
        tmp_path,
        config(path, retry={"enabled": True, "maxRetries": 3, "baseDelayMs": 0}),
        "/compact",
    )
    assert result.status == "error"
    assert count == 1
    assert path.read_bytes() == before


def test_pi_compaction_task_cancellation_never_commits_a_partial_checkpoint(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    before = path.read_bytes()

    async def scenario():
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        transport(monkeypatch, handler)
        task = asyncio.create_task(
            loop.compact(
                config(path),
                tmp_path,
                tmp_path,
                resources=ResourceBundle(system_prompt="system", tool_schemas=[]),
            )
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert path.read_bytes() == before


def test_pi_model_limits_use_release_catalog_and_explicit_role_overrides():
    assert model_limits({"llm": {"model_name": "openai/gpt-5"}}) == (400000, 128000)
    assert model_limits(
        {
            "llm": {"model_name": "gpt-5", "provider_name": "openai"},
            "context_window": 1000,
            "model_max_tokens": 50,
        }
    ) == (1000, 50)


@pytest.mark.parametrize("value", [-1, 0.5, float("nan"), 2**53, True])
def test_pi_compaction_token_settings_require_nonnegative_safe_integer(tmp_path, value):
    with pytest.raises(ValueError, match="safe integer"):
        settings(config(compaction={"reserveTokens": value}), tmp_path)


@pytest.mark.parametrize("keep", [0, 11])
def test_pi_truncated_response_recovery_compacts_once_and_preserves_new_prompt(
    tmp_path, monkeypatch, keep
):
    path = seed(tmp_path)
    requests, summaries = [], []

    def handler(request):
        payload = json.loads(request.content)
        if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT:
            summaries.append(payload)
            return completion("truncation checkpoint")
        requests.append(payload)
        if len(requests) == 1:
            return completion(
                "partial",
                reason="length",
                usage={**ZERO, "output": 2, "totalTokens": 2},
            )
        return completion(
            "recovered answer", usage={**ZERO, "input": 5, "totalTokens": 5}
        )

    transport(monkeypatch, handler)
    result = run(
        tmp_path, config(path, compaction={"keepRecentTokens": keep}), "new prompt"
    )
    assert result.status == "finished"
    assert result.output == "recovered answer"
    assert len(requests) == 2
    assert summaries
    session = Session(tmp_path, path)
    checkpoint = next(e for e in session.entries if e["type"] == "compaction")
    assert checkpoint["firstKeptEntryId"] in {e["id"] for e in session.entries}
    assert "compaction-recovery-draft" not in path.read_text()
    assert "partial" not in json.dumps(requests[-1]["messages"])


def test_pi_split_summary_second_call_failure_keeps_entire_original_session(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    before = path.read_bytes()
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return completion(
            "history summary" if count == 1 else "incomplete prefix",
            reason="stop" if count == 1 else "length",
        )

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path, compaction={"keepRecentTokens": 3}), "/compact")
    assert result.status == "error"
    assert count == 2
    assert path.read_bytes() == before


def test_pi_branch_summary_is_connected_to_native_loop_and_persistent_resume(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return completion(
            "branch checkpoint"
            if payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT
            else "new branch answer"
        )

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path), "/tree e2 preserve files")
    assert result.status == "finished"
    assert "branch checkpoint" in result.output
    session = Session(tmp_path, path)
    assert session.entries[-1]["type"] == "branch_summary"
    assert session.entries[-1]["parentId"] == "e2"
    assert session.entries[-1]["fromId"] == "e4"
    resumed = run(tmp_path, config(path, compaction=False), "new branch prompt")
    assert resumed.status == "finished"
    sent = json.dumps(requests[-1]["messages"])
    assert "branch checkpoint" in sent
    assert "current task" not in sent
    assert "new branch prompt" in sent


def test_pi_tree_navigation_without_summary_persists_selected_leaf(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion("done")

    transport(monkeypatch, handler)
    result = run(tmp_path, config(path, branch_summary=False), "/tree e2")
    assert result.status == "finished"
    assert not requests
    session = Session(tmp_path, path)
    assert session.entries[-1]["parentId"] == "e2"
    result = run(tmp_path, config(path, compaction=False), "continued")
    assert result.status == "finished"
    assert "current task" not in json.dumps(requests[-1]["messages"])


def test_pi_summary_usage_is_included_in_total_usage(tmp_path, monkeypatch):
    path = seed(tmp_path)
    transport(
        monkeypatch,
        lambda request: completion(
            "checkpoint", usage={**ZERO, "input": 10, "output": 2, "totalTokens": 12}
        ),
    )
    result = run(tmp_path, config(path), "/compact")
    assert result.status == "finished"
    assert result.usage["model_calls"] == 1
    assert result.usage["summary_calls"] == 1
    assert result.usage["input_tokens"] == 10
    assert result.usage["output_tokens"] == 2
    assert result.usage["total_tokens"] == 12


def test_pi_adapter_compaction_executes_snapshot_runtime_and_includes_catalog(
    tmp_path, monkeypatch
):
    from flashrsi.agents.pi_agent import Pi

    path = seed(tmp_path)
    transport(monkeypatch, lambda request: completion("snapshot checkpoint"))
    agent = Pi(config(path))
    assert "runtime/pi_native/compaction.py" in agent.snapshot.files
    assert "runtime/pi_native/model_limits.json" in agent.snapshot.files
    result = asyncio.run(agent.compact(tmp_path))
    assert result.status == "finished"
    assert result.output == "snapshot checkpoint"
    assert Session(tmp_path, path).entries[-1]["type"] == "compaction"


@pytest.mark.parametrize(
    "api", ["openai-completions", "openai-responses", "anthropic-messages"]
)
def test_pi_all_summary_provider_routes_use_explicit_caller_credentials_and_resume(
    api, tmp_path, monkeypatch
):
    path = seed(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "host-openai-key-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "host-anthropic-key-must-not-be-used")
    requests = []
    provider = "anthropic" if api == "anthropic-messages" else "openai"
    cfg = config(path)
    cfg["llm"].update(
        model_name=f"{provider}/oracle",
        model_api=api,
        api_key="explicit-caller-role-key",
        headers={"X-Caller-Route": "role-config"},
    )

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.headers["X-Caller-Route"] == "role-config"
        if api == "anthropic-messages":
            assert request.url.path == "/v1/messages"
            assert request.headers["x-api-key"] == "explicit-caller-role-key"
            assert payload["max_tokens"] == 4096
            assert "tools" not in payload
            if len(requests) == 1:
                assert content_text(payload["system"]) == SUMMARIZATION_SYSTEM_PROMPT
                assert "<conversation>" in content_text(
                    payload["messages"][0]["content"]
                )
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "provider checkpoint"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            )
        assert request.headers["Authorization"] == "Bearer explicit-caller-role-key"
        if api == "openai-responses":
            assert request.url.path == "/v1/responses"
            assert payload["max_output_tokens"] == 4096 if len(requests) == 1 else True
            assert payload["store"] is False
            assert "tools" not in payload
            if len(requests) == 1:
                assert payload["input"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT
                assert "<conversation>" in payload["input"][1]["content"][0]["text"]
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": "provider checkpoint"}
                            ],
                        }
                    ],
                    "status": "completed",
                    "usage": {"input_tokens": 5, "output_tokens": 1},
                },
            )
        assert request.url.path == "/v1/chat/completions"
        if len(requests) == 1:
            assert payload["messages"][0]["content"] == SUMMARIZATION_SYSTEM_PROMPT
            assert payload["max_completion_tokens"] == 4096
            assert "tools" not in payload
        return completion(
            "provider checkpoint",
            usage={**ZERO, "input": 5, "output": 1, "totalTokens": 6},
        )

    transport(monkeypatch, handler)
    result = run(tmp_path, cfg, "/compact")
    assert result.status == "finished"
    assert result.output == "provider checkpoint"
    assert result.usage["total_tokens"] == 6
    cfg["compaction"] = False
    resumed = run(tmp_path, cfg, "continue with checkpoint")
    assert resumed.status == "finished"
    assert "provider checkpoint" in json.dumps(requests[-1])
    assert "continue with checkpoint" in json.dumps(requests[-1])


@pytest.mark.parametrize(
    "update",
    [
        {"compaction": {"keep_recent_token": 5}},
        {"compaction": {"model": "unexpected-model"}},
        {"branch_summary": {"output_tokens": 2}},
        {"retry": {"attempts": 5}},
        {"retry": {"provider": {"retry_cap": 5}}},
        {"session": {"session_file": "typo.jsonl"}},
    ],
)
def test_pi_unknown_compression_options_fail_before_session_side_effects(
    tmp_path, monkeypatch, update
):
    path = tmp_path / "not-created.jsonl"
    transport(
        monkeypatch,
        lambda request: pytest.fail("invalid settings must not make a model request"),
    )
    with pytest.raises(ValueError):
        run(tmp_path, config(path, **update), "/compact")
    assert not path.exists()


def test_pi_manual_compaction_cannot_inherit_host_credentials(tmp_path, monkeypatch):
    path = seed(tmp_path)
    before = path.read_bytes()
    monkeypatch.setenv("OPENAI_API_KEY", "host-key")
    cfg = config(path)
    del cfg["llm"]["api_key"]
    with pytest.raises(ValueError, match="api_key"):
        run(tmp_path, cfg, "/compact")
    assert path.read_bytes() == before


def test_pi_empty_manual_compaction_does_not_create_a_session_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "not-created.jsonl"
    transport(
        monkeypatch,
        lambda request: pytest.fail("empty compaction must not request a summary"),
    )
    result = run(tmp_path, config(path), "/compact")
    assert result.status == "error"
    assert not path.exists()


def test_pi_snapshot_provider_retry_options_reach_summary_transport(
    tmp_path, monkeypatch
):
    path = seed(tmp_path)
    directory = tmp_path / ".pi" / "agent"
    directory.mkdir(parents=True)
    (directory / "settings.json").write_text(
        json.dumps(
            {
                "retry": {
                    "enabled": False,
                    "provider": {
                        "maxRetries": 0,
                        "timeoutMs": 250,
                        "maxRetryDelayMs": 0,
                    },
                }
            }
        )
    )
    cfg = config(path)
    cfg["llm"].pop("max_retries")
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        assert request.extensions["timeout"]["read"] == 0.25
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    transport(monkeypatch, handler)
    result = run(tmp_path, cfg, "/compact")
    assert result.status == "error"
    assert count == 1
