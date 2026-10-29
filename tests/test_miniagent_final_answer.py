import asyncio
from types import SimpleNamespace

import pytest

from flashrsi.agents.miniagent.runtime import agent, llm


@pytest.mark.parametrize("tag", ["tool_calls", "calls", " calls"])
@pytest.mark.parametrize("closed", [True, False])
@pytest.mark.parametrize("preamble", ["", "Let me verify the files next.\n"])
def test_residual_tool_markup_requires_a_real_final_answer(
    monkeypatch, tmp_path, tag, closed, preamble
):
    markup = preamble + f"<｜｜DSML｜｜{tag}>invoke shell"
    if closed:
        markup += f"</｜｜DSML｜｜{tag}>"
    calls = []

    async def chat(messages, **kwargs):
        calls.append((list(messages), kwargs))
        content = markup if len(calls) == 1 else "<DESIGN>Changed the prompt.</DESIGN>"
        return SimpleNamespace(
            id=f"call-{len(calls)}",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=None),
                    finish_reason="stop",
                )
            ],
        )

    monkeypatch.setattr(llm, "chat", chat)
    result = asyncio.run(
        agent.run("Describe the edit in DESIGN tags", runs_root=tmp_path, max_turns=1)
    )
    assert len(calls) == 2
    assert calls[1][1]["tool_choice"] == "none"
    assert "required format" in calls[1][0][-1]["content"]
    assert result["answer"] == "<DESIGN>Changed the prompt.</DESIGN>"
    assert result["stop_reason"] == "completed"
    assert [entry["role"] for entry in result["usage"]] == ["primary", "forced_answer"]


@pytest.mark.parametrize("preamble", ["", "Let me verify the files next.\n"])
def test_tool_markup_only_after_finalization_is_a_failure(
    monkeypatch, tmp_path, preamble
):
    async def chat(messages, **kwargs):
        return SimpleNamespace(
            id="call",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=preamble + "<｜｜DSML｜｜ calls>shell", tool_calls=None
                    ),
                    finish_reason="stop",
                )
            ],
        )

    monkeypatch.setattr(llm, "chat", chat)
    result = asyncio.run(agent.run("Finish editing", runs_root=tmp_path, max_turns=1))
    assert result["stop_reason"] == "llm_error: model returned no final answer text"
    assert result["answer"] == "(no answer produced)"


@pytest.mark.parametrize("content", ["  Paris\n", "<MANIFEST>{}</MANIFEST>"])
def test_plain_final_answer_does_not_request_another_call(
    monkeypatch, tmp_path, content
):
    calls = []

    async def chat(messages, **kwargs):
        calls.append(messages)
        return SimpleNamespace(
            id="call",
            usage=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content, tool_calls=None),
                    finish_reason="stop",
                )
            ],
        )

    monkeypatch.setattr(llm, "chat", chat)
    result = asyncio.run(agent.run("Answer", runs_root=tmp_path, max_turns=1))
    assert len(calls) == 1
    assert result["answer"] == content.strip()
    assert result["stop_reason"] == "completed"
