"""Recover DSML tool-call markup as native shell tool calls.

Some model backends emit tool calls as DSML text in the assistant message
instead of using the OpenAI ``tool_calls`` field.  When that happens the
runtime sees a plain-text final answer, the intended shell command is never
executed, and an AppWorld action task is graded as never completed.

This ``after_llm`` hook handles Chat Completions responses only.  It parses
``invoke name="shell"`` blocks, extracts the ``command`` parameter verbatim,
and returns a response whose native ``tool_calls`` contains that shell call so
the normal tool-call loop executes it.  Responses/API adapter objects are left
untouched: synthetic function calls there would corrupt provider-side call-id
history, and the existing final-answer gate still covers plain-text final
markup on that path.

The hook is deliberately conservative:

* it only fires for AppWorld-shaped questions (``Supervisor:`` /
  ``AppWorld tools are available``);
* it only fires on Chat Completions responses with no native tool calls;
* it never retries on its own.
"""

from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace
from typing import Any

_INVOKE_RE = re.compile(
    r"<[|｜]*DSML[|｜]*\s+invoke\s+name=\"(?P<name>[^\"]+)\"\s*>"
    r"(?P<body>.*?)</[|｜]*DSML[|｜]*\s+invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_COMMAND_PARAM_RE = re.compile(
    r"<[|｜]*DSML[|｜]*\s+parameter\s+name=\"command\"[^>]*>"
    r"(?P<command>.*?)</[|｜]*DSML[|｜]*\s+parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_OPEN_RE = re.compile(r"<[|｜]*DSML[|｜]*", re.IGNORECASE)


def _is_appworld(ctx) -> bool:
    question = getattr(ctx, "question", "") or ""
    if "AppWorld tools are available" in question:
        return True
    return "Supervisor:" in question and "Current simulated datetime:" in question


def _looks_like_chat_completion(resp: Any) -> bool:
    """True only for Chat Completions objects, not Responses/adapters."""
    if resp is None:
        return False
    if hasattr(resp, "output") or hasattr(resp, "_original_call_ids"):
        return False
    return bool(getattr(resp, "choices", None))


def _has_dsml_invoke(text: str) -> bool:
    lowered = (text or "").lower()
    return "dsml" in lowered and "invoke name=" in lowered


def _prefix_before_dsml(text: str) -> str:
    match = _DSML_OPEN_RE.search(text)
    if not match:
        return text
    return text[: match.start()].strip()


def _parse_dsml_shell_commands(text: str) -> list[str]:
    commands: list[str] = []
    for match in _INVOKE_RE.finditer(text):
        name = match.group("name") or ""
        if name != "shell":
            continue
        body = match.group("body") or ""
        param = _COMMAND_PARAM_RE.search(body)
        if not param:
            continue
        command = (param.group("command") or "").strip()
        if command:
            commands.append(command)
    return commands


def _make_shell_tool_call(call_id: str, command: str) -> Any:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name="shell",
            arguments=json.dumps({"command": command}, ensure_ascii=False),
        ),
    )


async def after_llm(resp: Any, ctx) -> Any:
    """Convert DSML-only Chat Completions output into native ``shell`` calls."""
    if not _is_appworld(ctx):
        return resp
    if not _looks_like_chat_completion(resp):
        return resp

    try:
        msg = resp.choices[0].message
    except (AttributeError, IndexError, TypeError):
        return resp

    content = getattr(msg, "content", None) or ""
    if not content:
        return resp

    existing_tool_calls = getattr(msg, "tool_calls", None) or []
    if existing_tool_calls:
        return resp

    if not _has_dsml_invoke(content):
        return resp

    try:
        commands = _parse_dsml_shell_commands(content)
    except Exception as e:
        ctx.trace.event("dsml_recovery_error", error=str(e))
        return resp

    if not commands:
        return resp

    tool_calls = [
        _make_shell_tool_call("dsml_" + uuid.uuid4().hex[:12], command)
        for command in commands
    ]
    new_message = SimpleNamespace(
        role="assistant",
        content=_prefix_before_dsml(content),
        reasoning_content=getattr(msg, "reasoning_content", None),
        tool_calls=tool_calls,
    )
    new_choice = SimpleNamespace(message=new_message, finish_reason="tool_calls")
    new_resp = SimpleNamespace(
        id=getattr(resp, "id", None),
        model=getattr(resp, "model", None),
        usage=getattr(resp, "usage", None),
        choices=[new_choice],
    )
    ctx.trace.event(
        "dsml_recovery",
        recovered=len(tool_calls),
        chars=len(content),
    )
    return new_resp
