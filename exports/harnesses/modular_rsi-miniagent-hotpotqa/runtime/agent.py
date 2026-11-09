"""
Workspace-aware ReAct loop.

The kernel:
  - Loads a workspace (agent.yaml + prompts + tool descriptions + extras).
  - Runs a ReAct loop with a budget (max_turns).
  - Dispatches tool calls: built-in (web_search/read_url)
    OR workspace-provided (workspace/tools/<name>.py).
  - Runs middleware hooks around each LLM turn and each tool call.

Built-in tool implementations live here; new tools are added by the proposer
in the workspace, NOT by editing this file.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import llm, reader
from . import web_config as web_settings
from . import workspace as ws_mod
from .tool_result import ToolResult
from .tools import web_search_structured
from .trace import TraceWriter
from .workspace import WorkspaceBundle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime context — passed to middleware hooks and workspace tools
# ---------------------------------------------------------------------------


@dataclass
class SearchRecord:
    idx: int
    query: str
    turn: int
    items: list
    urls: list


@dataclass
class ReadRecord:
    idx: int
    url: str
    focus: str
    turn: int
    success: bool
    failure_type: str | None
    artifact_path: str | None
    content_preview: str


@dataclass
class ToolCallRecord:
    seq: int
    requested_name: str
    requested_args: dict
    executed_name: str
    executed_args: dict
    turn: int
    result_preview: str
    result_metadata: dict = field(default_factory=dict)
    action: str = "executed"
    source: str = "model"


@dataclass
class Context:
    workspace: WorkspaceBundle
    trace: TraceWriter
    working_dir: Path = field(default_factory=Path.cwd)
    # ── identity / config ──
    question: str = ""
    run_id: str = ""
    run_dir: str = ""
    model: str = ""
    max_turns: int = 0
    # ── counters ──
    search_calls: int = 0
    read_calls: int = 0
    # ── structured history ──
    searches: list = field(default_factory=list)
    reads: list = field(default_factory=list)
    tool_history: list = field(default_factory=list)
    current_turn_calls: list = field(default_factory=list)
    # ── middleware state ──
    sub_agents: dict[str, Any] = field(default_factory=dict)
    state: dict = field(default_factory=lambda: defaultdict(dict))
    memory: list = field(default_factory=list)
    # ── internal ──
    _current_turn: int = 0
    _tool_seq: int = 0
    _side_llm_calls: int = 0
    _side_llm_max: int = 20
    _in_injected_call: bool = False
    _pending_injections: list = field(default_factory=list)
    _tool_skips: int = 0
    _tool_redirects: int = 0
    _injections_count: int = 0
    _final_continues: int = 0
    _final_continue_max: int = 3
    model_usage: list = field(default_factory=list)

    @property
    def turn(self) -> int:
        return self._current_turn

    @property
    def elapsed_s(self) -> float:
        return round(time.time() - self.trace._t0, 1)

    @property
    def remaining_turns(self) -> int:
        return max(0, self.max_turns - self._current_turn)

    async def side_text(
        self, prompt: str, *, purpose: str, max_tokens: int = 500
    ) -> str | None:
        if self._side_llm_calls >= self._side_llm_max:
            self.trace.event("side_llm_budget_exceeded", budget=self._side_llm_max)
            return None
        self._side_llm_calls += 1
        capped = min(max_tokens, 500)
        started = time.monotonic()
        try:
            result, response = await llm.text(
                prompt,
                model=llm.SIDE_MODEL,
                max_tokens=capped,
                _return_response=True,
            )
        except Exception as e:
            self.trace.event(
                "side_llm_error",
                call_n=self._side_llm_calls,
                purpose=purpose,
                error=str(e),
            )
            return None
        self.trace.event(
            "side_llm",
            call_n=self._side_llm_calls,
            purpose=purpose,
            prompt_len=len(prompt),
            result_len=len(result),
        )
        usage = {
            "role": "side",
            "call_n": self._side_llm_calls,
            "model": llm.SIDE_MODEL,
            "call_id": getattr(response, "id", None),
            "latency_seconds": time.monotonic() - started,
            "usage": llm.usage_dict(response),
        }
        self.model_usage.append(usage)
        self.trace.event("model_usage", **usage)
        return result


# ---------------------------------------------------------------------------
# Built-in tool dispatch
# ---------------------------------------------------------------------------


def _serialize_assistant(msg) -> dict:
    """Convert an LLM response Message into a plain dict for the next request.

    Preserves `reasoning_content` for models that require it on tool round-trips. Strips
    fields the API rejects on input (`refusal`, `audio`, etc.)."""
    if hasattr(msg, "model_dump"):
        d = msg.model_dump(exclude_none=True)
    elif hasattr(msg, "dict"):
        d = msg.dict(exclude_none=True)
    else:
        d = {"role": getattr(msg, "role", "assistant")}
        if getattr(msg, "content", None) is not None:
            d["content"] = msg.content
        if getattr(msg, "reasoning_content", None) is not None:
            d["reasoning_content"] = msg.reasoning_content
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tcs
            ]
    if "tool_calls" in d and "content" not in d:
        d["content"] = ""
    for k in (
        "function_call",
        "audio",
        "annotations",
        "refusal",
        "provider_specific_fields",
    ):
        d.pop(k, None)
    return d


def _obj_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _make_chat_tool_call(call_id: str, name: str, arguments: str):
    """Create a chat-completions-shaped tool call object."""
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _responses_call_to_chat_tool_call(fc: Any):
    call_id = (
        _obj_get(fc, "call_id")
        or _obj_get(fc, "id")
        or _obj_get(fc, "tool_call_id")
        or ""
    )
    name = _obj_get(fc, "name") or _obj_get(_obj_get(fc, "function", {}), "name") or ""
    arguments = (
        _obj_get(fc, "arguments")
        or _obj_get(_obj_get(fc, "function", {}), "arguments")
        or "{}"
    )
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return _make_chat_tool_call(call_id, name, arguments)


def _chat_tool_call_to_common(tc: Any, *, injected: bool = False) -> dict:
    fn = _obj_get(tc, "function", {}) or {}
    args = _obj_get(fn, "arguments", "{}") or "{}"
    if not isinstance(args, str):
        args = json.dumps(args, ensure_ascii=False)
    out = {
        "id": _obj_get(tc, "id", "") or "",
        "name": _obj_get(fn, "name", "") or "",
        "arguments": args,
    }
    if injected:
        out["injected"] = True
    return out


class _ResponsesMiddlewareAdapter:
    """Chat-like response facade for middleware on Responses API runs."""

    def __init__(
        self,
        raw: Any,
        content: str,
        reasoning: str,
        function_calls: list,
        *,
        original_call_ids: set[str] | None = None,
    ):
        self.raw_response = raw
        self._content = content or ""
        self._reasoning_content = reasoning or ""
        self._reasoning = reasoning or ""
        self._tool_calls = [
            _responses_call_to_chat_tool_call(fc) for fc in function_calls
        ]
        if original_call_ids is None:
            original_call_ids = {
                _obj_get(tc, "id", "") or "" for tc in self._tool_calls
            }
        self._original_call_ids = set(original_call_ids)
        self.choices = [
            SimpleNamespace(
                message=SimpleNamespace(
                    role="assistant",
                    content=self._content,
                    reasoning_content=self._reasoning_content,
                    tool_calls=self._tool_calls,
                ),
                finish_reason="tool_calls" if self._tool_calls else "stop",
            )
        ]

    @property
    def content(self) -> str:
        return self._content

    @content.setter
    def content(self, value: str | None) -> None:
        self._content = value or ""
        try:
            self.choices[0].message.content = self._content
        except (AttributeError, IndexError, TypeError):
            pass

    @property
    def reasoning_content(self) -> str:
        return self._reasoning_content

    @reasoning_content.setter
    def reasoning_content(self, value: str | None) -> None:
        self._reasoning_content = value or ""
        try:
            self.choices[0].message.reasoning_content = self._reasoning_content
        except (AttributeError, IndexError, TypeError):
            pass

    @property
    def reasoning(self) -> str:
        return self._reasoning

    @reasoning.setter
    def reasoning(self, value: str | None) -> None:
        self._reasoning = value or ""

    @property
    def tool_calls(self) -> list:
        return self._tool_calls

    @tool_calls.setter
    def tool_calls(self, value: list | None) -> None:
        self._tool_calls = list(value or [])
        try:
            self.choices[0].message.tool_calls = self._tool_calls
            self.choices[0].finish_reason = "tool_calls" if self._tool_calls else "stop"
        except (AttributeError, IndexError, TypeError):
            pass

    def sync_from_message(self) -> None:
        msg = self.choices[0].message
        msg_content = getattr(msg, "content", None)
        if msg_content is not None:
            self._content = msg_content
        elif getattr(self, "content", None) is not None:
            msg.content = self._content
        msg_reasoning = getattr(msg, "reasoning_content", None)
        if msg_reasoning is not None:
            self._reasoning_content = msg_reasoning
            self._reasoning = self._reasoning or msg_reasoning
        msg_tool_calls = getattr(msg, "tool_calls", None)
        self._tool_calls = list(msg_tool_calls or [])
        msg.tool_calls = self._tool_calls

    def common_tool_calls(self) -> list[dict]:
        self.sync_from_message()
        out: list[dict] = []
        for tc in self.tool_calls:
            call_id = _obj_get(tc, "id", "") or ""
            out.append(
                _chat_tool_call_to_common(
                    tc,
                    injected=call_id not in self._original_call_ids,
                )
            )
        return out


def _ensure_responses_adapter(
    response: Any,
    *,
    original_call_ids: set[str],
) -> _ResponsesMiddlewareAdapter:
    """Normalize middleware return values back into the Responses facade."""
    if isinstance(response, _ResponsesMiddlewareAdapter):
        return response

    choices = getattr(response, "choices", None)
    if choices:
        msg = choices[0].message
        adapter = _ResponsesMiddlewareAdapter(
            response,
            getattr(msg, "content", None) or getattr(response, "content", "") or "",
            getattr(msg, "reasoning_content", None)
            or getattr(response, "reasoning_content", None)
            or getattr(response, "reasoning", None)
            or "",
            [],
            original_call_ids=original_call_ids,
        )
        adapter.choices = choices
        adapter.sync_from_message()
        return adapter

    if getattr(response, "output", None) is not None:
        content, reasoning, function_calls = llm.extract_responses_output(response)
        return _ResponsesMiddlewareAdapter(
            response,
            content,
            reasoning,
            function_calls,
            original_call_ids=original_call_ids,
        )

    adapter = _ResponsesMiddlewareAdapter(
        response,
        getattr(response, "content", None) or "",
        getattr(response, "reasoning_content", None)
        or getattr(response, "reasoning", None)
        or "",
        [],
        original_call_ids=original_call_ids,
    )
    adapter.tool_calls = list(getattr(response, "tool_calls", None) or [])
    return adapter


def _middleware_message_key(msg: Any) -> str:
    try:
        return json.dumps(msg, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(msg)


def _middleware_additions(before: list, after: list) -> list:
    """Return messages added by before_llm hooks, even if hooks copied lists."""
    remaining: dict[str, int] = {}
    for msg in before:
        key = _middleware_message_key(msg)
        remaining[key] = remaining.get(key, 0) + 1

    added = []
    for msg in after:
        key = _middleware_message_key(msg)
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
        else:
            added.append(msg)
    return added


def _responses_input_from_middleware_message(msg: Any) -> dict | None:
    role = _obj_get(msg, "role", "") or ""
    content = _obj_get(msg, "content", "") or ""
    if not content or role not in {"system", "developer", "user", "assistant"}:
        return None
    # Responses API already receives the main system prompt via instructions;
    # runtime middleware nudges are safest as developer messages.
    if role == "system":
        role = "developer"
    return {"role": role, "content": content}


def _middleware_assistant_message(content: str, tc_list: list[dict]) -> dict:
    msg = {"role": "assistant", "content": content or ""}
    if tc_list:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            }
            for tc in tc_list
        ]
    return msg


async def _dispatch_builtin(name: str, args: dict, ctx: Context) -> str | None:
    """Returns a string result for built-ins; None if `name` is not built-in."""
    if name == "web_search":
        ctx.search_calls += 1
        query = (args.get("query") or "").strip()
        if not query:
            return "web_search requires a non-empty `query`."
        result_text, items = await web_search_structured(query)
        ctx.trace.save_search(ctx.search_calls, query, result_text)
        urls = [item["url"] for item in items]
        ctx.searches.append(
            SearchRecord(
                idx=ctx.search_calls,
                query=query,
                turn=ctx._current_turn,
                items=items,
                urls=urls,
            )
        )
        return result_text

    if name == "read_url":
        ctx.read_calls += 1
        url = (args.get("url") or "").strip()
        focus = (args.get("focus") or "").strip()
        if not url:
            return "read_url requires a non-empty `url`."
        page = await reader.read_url_with_raw(
            url,
            focus or "general relevance",
            extract_prompt=ctx.workspace.extract_prompt,
        )
        extracted = page["extracted"]
        artifact_path = ctx.trace.save_page(
            url, focus, extracted, raw_text=page.get("raw", "")
        )
        success = True
        failure_type = None
        if "[reader] fetch failed" in extracted:
            success, failure_type = False, "fetch_failed"
        elif "[reader] extract error" in extracted:
            success, failure_type = False, "extract_error"
        elif "[reader] no relevant content" in extracted:
            success, failure_type = False, "no_content"
        ctx.reads.append(
            ReadRecord(
                idx=ctx.read_calls,
                url=url,
                focus=focus,
                turn=ctx._current_turn,
                success=success,
                failure_type=failure_type,
                artifact_path=artifact_path,
                content_preview=extracted[:500],
            )
        )
        return extracted

    return None


def _normalize_tool_result(value: Any, ctx: Context, *, tool: str) -> tuple[str, dict]:
    """Normalize custom workspace tool returns into content + metadata."""
    if isinstance(value, ToolResult):
        metadata = value.metadata if isinstance(value.metadata, dict) else {}
        if value.metadata is not metadata:
            ctx.trace.event(
                "tool_result_warning", tool=tool, reason="metadata_not_dict"
            )
        return str(value.content), copy.deepcopy(metadata)
    if isinstance(value, str):
        return value, {}
    if value is None:
        ctx.trace.event("tool_result_warning", tool=tool, reason="none_return")
        return "", {}
    ctx.trace.event(
        "tool_result_warning",
        tool=tool,
        reason=f"unexpected_return_type: {type(value).__name__}",
    )
    return str(value), {}


async def _run_before_final_hooks(
    candidate: str, ctx: Context
) -> tuple[str, str, str | None]:
    """Run final-answer gates. Returns (action, answer, feedback)."""
    answer = candidate
    for mw in ctx.workspace.middlewares:
        hook = getattr(mw, "before_final", None)
        if not hook:
            continue
        try:
            ret = await hook(answer, ctx)
        except Exception as e:
            ctx.trace.event(
                "middleware_error", hook="before_final", mw=mw.name, error=str(e)
            )
            continue

        if ret is None:
            ctx.trace.event("before_final_accept", mw=mw.name, mode="implicit")
            continue
        if not isinstance(ret, dict):
            ctx.trace.event(
                "middleware_warning",
                hook="before_final",
                mw=mw.name,
                reason=f"unexpected_return_type: {type(ret).__name__}",
            )
            continue

        action = ret.get("action", "accept")
        if action == "accept":
            ctx.trace.event("before_final_accept", mw=mw.name, mode="explicit")
            continue

        if action == "replace":
            if "answer" not in ret:
                ctx.trace.event(
                    "middleware_warning",
                    hook="before_final",
                    mw=mw.name,
                    reason="replace_missing_answer",
                )
                continue
            answer = str(ret.get("answer") or "")
            ctx.trace.event("before_final_replace", mw=mw.name, length=len(answer))
            continue

        if action == "continue":
            feedback = ret.get("feedback")
            if not isinstance(feedback, str) or not feedback.strip():
                ctx.trace.event(
                    "middleware_warning",
                    hook="before_final",
                    mw=mw.name,
                    reason="continue_missing_feedback",
                )
                continue
            if ctx.remaining_turns <= 0:
                ctx.trace.event(
                    "before_final_continue_rejected", mw=mw.name, reason="last_turn"
                )
                return "accept", answer, None
            if ctx._final_continues >= ctx._final_continue_max:
                ctx.trace.event(
                    "before_final_continue_rejected",
                    mw=mw.name,
                    reason="budget_exceeded",
                    budget=ctx._final_continue_max,
                )
                return "accept", answer, None
            ctx._final_continues += 1
            ctx.trace.event(
                "before_final_continue",
                mw=mw.name,
                count=ctx._final_continues,
                feedback=feedback,
            )
            return "continue", answer, feedback

        ctx.trace.event(
            "middleware_warning",
            hook="before_final",
            mw=mw.name,
            reason=f"unknown_action: {action}",
        )

    return "accept", answer, None


def _strip_final_answer_padding(text: str) -> str:
    """Remove markdown/list/heading and common explanatory padding from a final answer.

    The order matters: markdown and trailing sign-offs are removed before an
    explicit ``Final Answer:`` line is extracted. This allows bold answer labels
    to be recognized and prevents a numeric short answer such as ``1971.`` from
    being mistaken for a numbered-list marker.
    """
    text = text.strip()
    if not text:
        return text

    # Drop fenced code blocks but keep their text content.
    text = re.sub(r"```(?:[A-Za-z0-9_+.-]*)?\s*", "", text)

    # Remove markdown emphasis and heading markers before looking for an
    # explicit final-answer line so "**Final Answer:** 1971" is handled.
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)

    # Remove common trailing sign-offs before extracting the answer line.
    # Otherwise a sign-off on the same line keeps the explicit-answer regex
    # from ending at the answer span.
    text = re.sub(
        r"\s+(?:i hope this helps|hope this helps|"
        r"let me know if you have(?: any)? questions|"
        r"let me know if you need(?: anything)?(?: else)?|"
        r"does this help|feel free to ask).*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Prefer an explicit final-answer line when present.
    explicit = re.search(
        r"(?im)^\s*(?:the\s+)?(?:final\s+|correct\s+)?answer\s*[:：-]\s*(.+?)\s*$",
        text,
    )
    if explicit:
        text = explicit.group(1).strip()
    else:
        # Strip a leading "The answer is ..." style wrapper.
        text = re.sub(
            r"^\s*(?:the\s+)?(?:final\s+|correct\s+)?answer\s*(?:is|:)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        # Strip a fuller "Based on the context, the answer is ..." wrapper.
        text = re.sub(
            r"^\s*(?:based on|according to)\s+(?:the\s+)?"
            r"(?:context|passage|text|article|document|evidence)[,:]?\s+"
            r"(?:the\s+)?(?:final\s+|correct\s+)?answer\s*(?:is|:)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

    # Remove bullet list markers. Numbered list markers are only stripped when
    # the text is a true multi-line numbered list; this prevents a numeric
    # answer such as "1971." from being mistaken for a list marker.
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    lines = text.splitlines()
    non_empty = [line for line in lines if line.strip()]
    numbered = [line for line in non_empty if re.match(r"^\s*\d+[.)]\s+", line)]
    if len(non_empty) >= 2 and len(numbered) == len(non_empty):
        text = re.sub(r"(?m)^\s*\d+[.)]\s+", "", text)

    text = re.sub(r"\s+", " ", text).strip()
    # Bare numeric short answers should not carry a trailing sentence period
    # or list parenthesis (e.g. "1971." -> "1971", "13)" -> "13").
    text = re.sub(r"^(\d+)[.)]$", r"\1", text)
    text = re.sub(r"^(\d+(?:[-\u2013\u2014]\d+)+)[.)]$", r"\1", text)
    return text


def _message_text_content(content: Any) -> str:
    """Normalize Chat Completions message content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                part = item.get("text") or ""
            else:
                part = str(item)
            if part:
                parts.append(part)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _completion_check_evidence(
    messages: list[dict], question: str, *, max_chars: int = 16000
) -> str:
    """Collect the conversation evidence for the side-model completion check.

    The original question is passed separately, so the initial user message is
    omitted. System prompts are omitted because they are instructions, not
    evidence. Tool results, tool calls, and prior feedback are retained.
    """
    lines: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "system":
            continue
        content = _message_text_content(msg.get("content")).strip()
        if role == "user" and content == question.strip():
            continue
        if not content:
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                try:
                    content = json.dumps(tool_calls, ensure_ascii=False)
                except Exception:
                    content = repr(tool_calls)
        if not content:
            continue
        lines.append(f"[{role}] {content}")
    evidence = "\n".join(lines).strip()
    if len(evidence) <= max_chars:
        return evidence
    head_chars = 2000
    tail_chars = max_chars - head_chars
    return (
        evidence[:head_chars]
        + "\n...[truncated]...\n"
        + evidence[-tail_chars:]
    )


def _completion_check_prompt(
    question: str, candidate: str, messages: list[dict]
) -> str:
    """Build the side-model prompt that validates a candidate final answer."""
    evidence = _completion_check_evidence(messages, question)
    return (
        "You are the task-completion detector for another assistant. "
        "Decide whether the candidate final answer is the exact, concise short answer "
        "to the original question, using the supplied context and evidence.\n"
        "\n"
        "Original question:\n"
        f"<question>\n{question.strip()}\n</question>\n"
        "\n"
        "Gathered evidence (may be empty):\n"
        f"<evidence>\n{evidence or '(no gathered evidence)'}\n</evidence>\n"
        "\n"
        "Candidate final answer:\n"
        f"<candidate>\n{candidate.strip()}\n</candidate>\n"
        "\n"
        "Output exactly three lines and nothing else:\n"
        "ACTION: <accept|correct|continue>\n"
        "ANSWER: <exact short answer if accept or correct, otherwise leave empty>\n"
        "FEEDBACK: <targeted guidance if continue, otherwise leave empty>\n"
        "\n"
        "Rules:\n"
        '- "accept": the candidate is already the exact concise short answer '
        "(no explanation, no extra qualifiers, no missing units, names, ordinals, or cardinals).\n"
        '- "correct": the candidate is close, verbose, or has minor formatting problems, '
        "and the evidence supports one exact short answer. Put that exact answer in ANSWER.\n"
        '- "continue": the candidate is wrong, incomplete, unsupported, or is an explanation/refusal '
        "instead of the short answer. Put one specific instruction in FEEDBACK telling the assistant "
        "exactly what to output, including the correct names, numbers, and units from the evidence when possible.\n"
        "- Never invent facts. If the evidence is insufficient to produce the exact answer, "
        'action must be "continue" with feedback about the missing fact.'
    )


def _parse_completion_check(raw: str) -> dict | None:
    """Parse the side model's ACTION/ANSWER/FEEDBACK response.

    JSON is accepted first for compatibility; the normal line format is parsed
    by looking for the three labels and collecting any following lines into the
    ANSWER or FEEDBACK value until the next label.
    """
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "").strip()

    # Accept a JSON object whether it is the whole payload or embedded in a
    # sentence. This keeps the parser tolerant of chatty side models.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "action" in data:
            return data
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict) and "action" in data:
                    return data
            except Exception:
                pass

    action: str | None = None
    answer_lines: list[str] = []
    feedback_lines: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(
            r"^\s*(?:[-*]+\s*)?ACTION\s*:\s*[-*]*\s*(accept|correct|continue)\b",
            stripped,
            re.I,
        )
        if m:
            action = m.group(1).lower()
            current = None
            continue
        m = re.match(
            r"^\s*(?:[-*]+\s*)?ANSWER\s*:\s*[-*]*\s*(.*)$", stripped, re.I
        )
        if m:
            current = "answer"
            answer_lines.append(m.group(1))
            continue
        m = re.match(
            r"^\s*(?:[-*]+\s*)?FEEDBACK\s*:\s*[-*]*\s*(.*)$", stripped, re.I
        )
        if m:
            current = "feedback"
            feedback_lines.append(m.group(1))
            continue
        if current == "answer":
            answer_lines.append(line)
        elif current == "feedback":
            feedback_lines.append(line)
    if action is None:
        return None
    answer = "\n".join(x.strip() for x in answer_lines if x.strip()).strip()
    feedback = "\n".join(x.strip() for x in feedback_lines if x.strip()).strip()
    return {"action": action, "answer": answer, "feedback": feedback}


async def _run_completion_check(
    candidate: str, ctx: Context, messages: list[dict]
) -> tuple[str, str, str | None]:
    """Validate and, when possible, correct a candidate final answer.

    This is a built-in task-completion gate. It uses the side-model path already
    available on ``Context`` so it does not add a new model or credential path.
    """
    prompt = _completion_check_prompt(ctx.question, candidate, messages)
    raw = await ctx.side_text(
        prompt,
        purpose="task_completion_detection",
        max_tokens=500,
    )
    if raw is None:
        ctx.trace.event(
            "completion_check_unavailable", candidate_length=len(candidate)
        )
        # Fall back to the pre-gate behaviour only when the validator cannot
        # run at all (side-model budget exhausted or side-model error).
        return "accept", candidate, None

    def _continue_or_accept(
        feedback: str, *, answer: str = ""
    ) -> tuple[str, str, str | None]:
        """Continue the loop with feedback while budget remains, else accept."""
        if ctx.remaining_turns <= 0:
            ctx.trace.event(
                "completion_check_continue_rejected", reason="last_turn"
            )
            return "accept", answer or candidate, None
        if ctx._final_continues >= ctx._final_continue_max:
            ctx.trace.event(
                "completion_check_continue_rejected",
                reason="budget_exceeded",
                budget=ctx._final_continue_max,
            )
            return "accept", answer or candidate, None
        ctx._final_continues += 1
        ctx.trace.event(
            "completion_check_continue",
            count=ctx._final_continues,
            feedback=feedback,
        )
        return "continue", candidate, feedback

    parsed = _parse_completion_check(raw)
    if parsed is None:
        ctx.trace.event(
            "completion_check_unparseable",
            candidate_length=len(candidate),
            raw=raw[:500],
        )
        return _continue_or_accept(
            "Your final answer could not be validated. Return only the exact "
            "short answer to the original question, with no explanation."
        )

    action = str(parsed.get("action", "")).strip().lower()
    answer = str(parsed.get("answer") or "").strip()
    feedback = str(parsed.get("feedback") or "").strip()

    if action == "correct":
        if answer:
            ctx.trace.event(
                "completion_check_corrected",
                before=candidate[:300],
                after=answer[:300],
            )
            return "accept", answer, None
        ctx.trace.event(
            "completion_check_corrected_missing_answer",
            candidate_length=len(candidate),
        )
        return _continue_or_accept(
            "Return only the exact short answer to the original question."
        )

    if action == "continue":
        if not feedback:
            feedback = (
                "Return only the exact short answer to the original question. "
                "Do not add explanation, units, suffixes, or extra qualifiers "
                "unless the question explicitly asks for them."
            )
        return _continue_or_accept(feedback, answer=answer)

    if action != "accept":
        ctx.trace.event("completion_check_unknown_action", action=action)
        return _continue_or_accept(
            "Return only the exact short answer to the original question."
        )

    ctx.trace.event("completion_check_accept", candidate_length=len(candidate))
    return "accept", candidate, None


async def _dispatch(name: str, args: dict, ctx: Context) -> str:
    if name not in ctx.workspace.tool_names:
        return f"Unavailable tool: {name}"
    original_name = name
    original_args = copy.deepcopy(args)
    action = "executed"
    skipped = False
    result = ""
    result_metadata: dict = {}

    # before_tool middlewares
    for mw in ctx.workspace.middlewares:
        if mw.before_tool:
            try:
                ret = await mw.before_tool(name, args, ctx)
                if isinstance(ret, dict):
                    act = ret.get("action")
                    if act == "skip":
                        if action == "redirected":
                            ctx.trace.event(
                                "middleware_warning",
                                hook="before_tool",
                                mw=mw.name,
                                reason="skip_after_redirect",
                            )
                        else:
                            result = str(ret.get("result", ""))
                            action = "skipped"
                            skipped = True
                            ctx._tool_skips += 1
                            ctx.trace.event(
                                "before_tool_skip", mw=mw.name, tool=original_name
                            )
                            break
                    elif act == "redirect":
                        new_name = ret.get("name")
                        new_args = ret.get("args")
                        if (
                            isinstance(new_name, str)
                            and new_name
                            and isinstance(new_args, dict)
                        ):
                            ctx.trace.event(
                                "before_tool_redirect",
                                mw=mw.name,
                                from_tool=original_name,
                                to_tool=new_name,
                            )
                            name, args = new_name, new_args
                            action = "redirected"
                            ctx._tool_redirects += 1
                        else:
                            ctx.trace.event(
                                "middleware_warning",
                                hook="before_tool",
                                mw=mw.name,
                                reason="invalid_redirect_payload",
                            )
                    else:
                        ctx.trace.event(
                            "middleware_warning",
                            hook="before_tool",
                            mw=mw.name,
                            reason=f"unknown_action: {act}",
                        )
                elif isinstance(ret, tuple):
                    if (
                        len(ret) == 2
                        and isinstance(ret[0], str)
                        and isinstance(ret[1], dict)
                    ):
                        name, args = ret
                    else:
                        ctx.trace.event(
                            "middleware_warning",
                            hook="before_tool",
                            mw=mw.name,
                            reason="invalid_tuple_return",
                        )
                elif ret is not None:
                    ctx.trace.event(
                        "middleware_warning",
                        hook="before_tool",
                        mw=mw.name,
                        reason=f"unexpected_return_type: {type(ret).__name__}",
                    )
            except Exception as e:
                ctx.trace.event(
                    "middleware_error", hook="before_tool", mw=mw.name, error=str(e)
                )

    # execution (skipped if before_tool set skip)
    if not skipped:
        if name not in ctx.workspace.tool_names:
            return f"Unavailable tool: {name}"
        builtin = await _dispatch_builtin(name, args, ctx)
        if builtin is not None:
            result = builtin
        elif name in ctx.workspace.extra_tools:
            try:
                raw_result = await ctx.workspace.extra_tools[name](args, ctx)
                result, result_metadata = _normalize_tool_result(
                    raw_result, ctx, tool=name
                )
            except Exception as e:
                result = f"workspace tool {name!r} error: {e}"
        else:
            result = f"Unknown tool: {name}"

    # after_tool middlewares
    for mw in ctx.workspace.middlewares:
        if mw.after_tool:
            try:
                ret = await mw.after_tool(name, args, result, ctx)
                if isinstance(ret, dict):
                    result = str(ret.get("result", result))
                    if "metadata" in ret:
                        if isinstance(ret["metadata"], dict):
                            result_metadata.update(copy.deepcopy(ret["metadata"]))
                        else:
                            ctx.trace.event(
                                "middleware_warning",
                                hook="after_tool",
                                mw=mw.name,
                                reason="metadata_not_dict",
                            )
                    inject_list = ret.get("inject", [])
                    if inject_list:
                        inj = inject_list[0]
                        if (
                            not isinstance(inj, dict)
                            or not isinstance(inj.get("name"), str)
                            or not inj["name"]
                            or not isinstance(inj.get("args", {}), dict)
                        ):
                            ctx.trace.event(
                                "after_tool_inject_rejected",
                                mw=mw.name,
                                reason="malformed_payload",
                            )
                        elif ctx._in_injected_call:
                            ctx.trace.event(
                                "after_tool_inject_rejected",
                                mw=mw.name,
                                reason="recursion_guard",
                            )
                        elif ctx._pending_injections:
                            ctx.trace.event(
                                "after_tool_inject_rejected",
                                mw=mw.name,
                                reason="one_per_turn",
                            )
                        else:
                            inj.setdefault("args", {})
                            ctx._pending_injections.append(inj)
                            ctx.trace.event(
                                "after_tool_inject_queued", mw=mw.name, tool=inj["name"]
                            )
                elif isinstance(ret, str):
                    result = ret
            except Exception as e:
                ctx.trace.event(
                    "middleware_error", hook="after_tool", mw=mw.name, error=str(e)
                )

    # record ToolCallRecord (single exit point)
    ctx._tool_seq += 1
    rec = ToolCallRecord(
        seq=ctx._tool_seq,
        requested_name=original_name,
        requested_args=original_args,
        executed_name=name,
        executed_args=copy.deepcopy(args),
        turn=ctx._current_turn,
        result_preview=result[:500],
        result_metadata=copy.deepcopy(result_metadata),
        action=action,
        source="middleware_inject" if ctx._in_injected_call else "model",
    )
    ctx.tool_history.append(rec)
    ctx.current_turn_calls.append(rec)
    return result


# ---------------------------------------------------------------------------
# Final-answer grounding helpers
# ---------------------------------------------------------------------------

_CONTEXT_LINE_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?"
    r"(?:context|passage|excerpt|article|document|text|information|evidence|"
    r"statement|description|scenario|source)s?"
    r"(?=\s*:|\s+|$)(?:\s*:)?\s*(.*)$"
)
_QUESTION_LINE_RE = re.compile(
    r"(?i)^\s*(?:#{1,6}\s*)?"
    r"(?:question|task|prompt|problem|instruction|query|user_query|user prompt|user message)"
    r"\b\s*:?\s*(.*)$"
)
_SHORT_QUESTION_START_RE = re.compile(
    r"(?i)^\s*(?:what|which|who|whom|whose|when|where)\b"
)
_SHORT_HOW_PHRASE_RE = re.compile(
    r"(?i)^\s*how\s+(?:many|much|old|far|long|often|tall|deep|wide|high|fast|soon)\b"
)
_SHORT_QUESTION_CUE_RE = re.compile(
    r"(?i)^\s*(?:name|identify|give|state|provide|find|extract|complete|answer)\b"
)
_SHORT_QUESTION_PREFIX_RE = re.compile(
    r"(?i)^(?:according to (?:the )?(?:context|passage|text|evidence|article)"
    r"|based on (?:the )?(?:context|passage|text|evidence|article))\s*,\s*"
)
_SHORT_QUESTION_WORD_RE = re.compile(
    r"(?i)\b(?:what|which|who|whom|whose|when|where)\b"
)
_EXPLANATION_START_RE = re.compile(
    r"(?i)^\s*(?:explain|describe|discuss|summarize|analyze|evaluate|compare|contrast)\b"
)
_YES_NO_QUESTION_START_RE = re.compile(
    r"(?i)^\s*(?:is|are|was|were|do|does|did|have|has|had|can|could|should|would|will|shall|may|might|must)\b"
)
_SHORT_ANSWER_INSTRUCTION_RE = re.compile(
    r"(?i)\b(?:short answer|briefly|one word|one sentence|a few words|answer with|answer in|return only|return the|state the|name the|give the|identify the|list the|choose the|select the|find the|extract the)\b"
)


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _strip_wrapping_quotes(text: str) -> str:
    text = text.strip()
    while len(text) >= 2 and text[0] in "\"'`" and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


def _parse_context_block(question: str) -> tuple[str, str]:
    """Return (context_text, question_text) parsed from a user message."""
    if not question:
        return "", ""
    lines = question.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = None
    inline = ""
    for i, line in enumerate(lines):
        m = _CONTEXT_LINE_RE.match(line)
        if m:
            start = i
            inline = (m.group(1) or "").strip()
            break
    if start is None:
        return "", question.strip()

    ctx_lines = [inline] if inline else []
    q_lines: list[str] = []
    header_found = False
    for j in range(start + 1, len(lines)):
        line = lines[j]
        hm = _QUESTION_LINE_RE.match(line)
        if hm:
            header_found = True
            rest = hm.group(1).strip()
            if rest:
                q_lines.append(rest)
            q_lines.extend(lines[j + 1 :])
            break
        ctx_lines.append(line.strip())

    context_text = "\n".join(x for x in ctx_lines if x).strip()
    if header_found:
        question_text = "\n".join(x for x in q_lines if x).strip()
    else:
        # No Question:/Task:/... header after the context block. It may still
        # precede the context; if so, use that as the question to evaluate.
        question_text = ""
        for i in range(start):
            hm = _QUESTION_LINE_RE.match(lines[i])
            if not hm:
                continue
            rest = hm.group(1).strip()
            q_parts = [rest] if rest else []
            q_parts.extend(x.strip() for x in lines[i + 1 : start] if x.strip())
            question_text = "\n".join(q_parts).strip()
            break
        if not question_text:
            question_text = "\n".join(lines[:start]).strip() or question.strip()
    return context_text, question_text


def _is_short_answer_question(question_text: str) -> bool:
    text = (question_text or "").strip()
    if not text:
        return False

    def _starts_short_question(value: str) -> bool:
        return bool(
            _SHORT_QUESTION_START_RE.match(value)
            or _SHORT_HOW_PHRASE_RE.match(value)
            or (_YES_NO_QUESTION_START_RE.match(value) and value.endswith("?"))
        )

    if _starts_short_question(text) or _SHORT_QUESTION_CUE_RE.match(text):
        return True

    stripped = _SHORT_QUESTION_PREFIX_RE.sub("", text, count=1).strip()
    if stripped != text and _starts_short_question(stripped):
        return True

    # Handles multi-sentence prompts such as "Answer the question: What is X?",
    # while avoiding explanation/essay commands such as "Explain why ...?" and
    # open-ended "why/how" questions.
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = sentence.strip()
        if not sentence or not sentence.endswith("?"):
            continue
        if _EXPLANATION_START_RE.match(sentence):
            continue
        if _starts_short_question(sentence):
            return True
        stripped_sentence = _SHORT_QUESTION_PREFIX_RE.sub(
            "", sentence, count=1
        ).strip()
        if (
            stripped_sentence != sentence
            and stripped_sentence.endswith("?")
            and _starts_short_question(stripped_sentence)
        ):
            return True
        if _SHORT_QUESTION_WORD_RE.search(sentence):
            return True
    return False


def _answer_text_equal(a: str, b: str) -> bool:
    a = _normalize_ws(_strip_wrapping_quotes(a or ""))
    b = _normalize_ws(_strip_wrapping_quotes(b or ""))
    return a == b and bool(a)


def _can_ground_span(span: str) -> bool:
    """Return True when a raw accepted answer is safe to normalize to a context slice.

    This predicate is deliberately conservative and is used only for raw
    accepted candidates. Single-token answers are kept as the model/detector
    produced them because a bare token can false-match or change case when
    normalized against context text. Multi-token names, titles, dates, and
    clauses are the spans that benefit from exact context normalization.
    """
    span = _normalize_ws(_strip_wrapping_quotes(span or ""))
    if not span:
        return False
    if span.lower() in {"yes", "no", "y", "n", "true", "false"}:
        return False
    return len(re.findall(r"\S+", span)) >= 2


def _span_in_context(span: str, context: str) -> str | None:
    """Locate `span` in `context` and return the exact context slice if present."""
    span = _normalize_ws(_strip_wrapping_quotes(span or ""))
    if not span:
        return None

    tokens = re.findall(r"\S+", span)
    token_variants = [tokens]
    if tokens:
        token_variants.append([t.rstrip(".,;:!?") for t in tokens])
    for toks in token_variants:
        if not toks:
            continue
        # Match whole tokens/phrases so short answers such as "China" cannot
        # false-match inside "Indochina" and single-word yes/no answers cannot
        # false-match inside longer words.
        pattern = (
            r"(?<![A-Za-z0-9])"
            + r"\s+".join(re.escape(tok) for tok in toks)
            + r"(?![A-Za-z0-9])"
        )
        try:
            m = re.search(pattern, context, flags=re.IGNORECASE)
            if m:
                return m.group(0)
        except re.error:
            pass

    ctx_ws = _normalize_ws(context)
    pattern = r"(?<![A-Za-z0-9])" + re.escape(span) + r"(?![A-Za-z0-9])"
    try:
        m = re.search(pattern, ctx_ws, flags=re.IGNORECASE)
        if m:
            return m.group(0)
    except re.error:
        pass
    return None


async def _extract_grounded_answer(
    ctx: Context, context_text: str, question_text: str
) -> str | None:
    prompt = (
        "You are a precise extraction assistant. Using ONLY the evidence below, "
        "find the exact complete answer to the question. Return the exact wording "
        "from the evidence. Do not paraphrase, shorten, expand, or add punctuation. "
        "Preserve complete multi-word names, locations, ordinals/dates, and complete "
        "clauses exactly as they appear in the evidence. Do not truncate or paraphrase "
        "a supported span. "
        "If the evidence does not contain the answer, return NONE.\n\n"
        "Evidence:\n```\n"
        f"{context_text}\n"
        "```\n\n"
        "Question:\n"
        f"{question_text}\n\n"
        "Exact answer:"
    )
    extracted = await ctx.side_text(
        prompt, purpose="final_answer_grounding", max_tokens=300
    )
    if not extracted:
        return None
    extracted = _normalize_ws(_strip_wrapping_quotes(extracted))
    extracted = re.sub(r"^```(?:[A-Za-z0-9_-]*)?\s*", "", extracted)
    extracted = re.sub(r"\s*```$", "", extracted).strip()
    extracted = re.sub(
        r"(?i)^(?:exact\s+answer|answer)\s*:\s*", "", extracted
    ).strip()
    if not extracted or extracted.upper() in {
        "NONE",
        "NO ANSWER",
        "NOT FOUND",
        "UNKNOWN",
        "N/A",
    }:
        return None
    return extracted or None


async def _run_final_answer_check(
    candidate: str, ctx: Context, messages: list[dict]
) -> tuple[str, str, str | None]:
    """Clean, validate, and ground a final answer before accepting it.

    This is the single built-in completion gate for the no-tool-call and forced
    answer paths. Short-answer candidates are cleaned and validated first; the
    task-completion detector is authoritative for accept/correct/continue. If
    it requests another model turn and a supplied context block can be parsed,
    a deterministic grounding extraction is attempted before looping.
    Long-form answers are accepted without being shortened.
    """
    context_text, question_text = _parse_context_block(ctx.question)
    question_for_check = question_text or ctx.question
    short_answer_requested = _is_short_answer_question(question_for_check) or bool(
        _SHORT_ANSWER_INSTRUCTION_RE.search(ctx.question or "")
    )
    if not short_answer_requested:
        # Preserve long-form answers; do not strip their structure or padding.
        return "accept", candidate, None

    try:
        cleaned = _strip_final_answer_padding(candidate)
        if not cleaned:
            cleaned = candidate
    except Exception:
        cleaned = candidate

    ctx.trace.event(
        "final_answer_check",
        candidate_len=len(cleaned),
        context_len=len(context_text),
    )

    # Primary gate: validate the cleaned candidate. This is intentionally run
    # before deterministic grounding so over-specific spans such as "two parts"
    # can be reduced to the requested short answer ("two").
    check_action, checked_answer, check_feedback = await _run_completion_check(
        cleaned, ctx, messages
    )

    if check_action == "accept":
        final_answer = checked_answer or cleaned
        if context_text and final_answer and _can_ground_span(final_answer):
            exact = _span_in_context(final_answer, context_text)
            if exact:
                exact = _normalize_ws(_strip_wrapping_quotes(exact))
                if exact:
                    return "accept", exact, None
        return "accept", final_answer, None

    # The detector wants another model turn. Before spending that turn, try to
    # ground the answer in the supplied context. This repairs truncated names
    # and titles, paraphrases, wrong ordinal/number forms, and refusals when
    # the evidence already contains the exact supported answer.
    if context_text:
        try:
            extracted = await _extract_grounded_answer(
                ctx, context_text, question_for_check
            )
        except Exception as e:
            ctx.trace.event("final_answer_grounding_error", error=str(e))
            extracted = None
        if extracted:
            # Extracted answers are grounded directly against the supplied
            # context. Single-token answers such as years, counts, and simple
            # nouns are allowed here because they came from the grounding
            # extractor rather than from the raw candidate.
            grounded = _span_in_context(extracted, context_text)
            if grounded:
                grounded = _normalize_ws(_strip_wrapping_quotes(grounded))
                if grounded and not _answer_text_equal(cleaned, grounded):
                    ctx.trace.event(
                        "final_answer_grounded_replaced",
                        candidate=cleaned[:300],
                        grounded=grounded[:300],
                    )
                    return "accept", grounded, None
        ctx.trace.event("final_answer_grounding_skipped", reason="span_not_verified")

    return "continue", cleaned, check_feedback


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run(
    question: str,
    *,
    runs_root: Path | str = "runs",
    max_turns: int = 100,
    model: str | None = None,
    workspace_dir: str | Path | None = None,
    editor: bool = False,
    working_dir: str | Path | None = None,
    llm_config: dict | None = None,
    web_config: dict | None = None,
    debug_llm_io: bool = False,
) -> dict[str, Any]:
    llm.configure(llm_config or {})
    web_settings.configure(web_config or {})
    runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)
    if editor:
        from .editor import bundle as editor_bundle

        bundle = editor_bundle(Path(workspace_dir))
    else:
        bundle = ws_mod.load(workspace_dir or ws_mod.SEED_WORKSPACE)
        from .web_config import validate_config

        validate_config(bundle.tool_names)
    if working_dir is not None:
        from .editor import attach

        attach(bundle, Path(working_dir))

    model = model or llm.DEFAULT_MODEL
    trace = TraceWriter(
        runs_root, question, config={"llm": llm_config, "web": web_config}
    )
    trace.event(
        "workspace",
        root=str(bundle.root),
        tools=bundle.tool_names,
        middlewares=[m.name for m in bundle.middlewares],
        sub_agents=list(bundle.sub_agents.keys()),
    )
    ctx = Context(
        workspace=bundle,
        trace=trace,
        working_dir=Path(working_dir).resolve() if working_dir else Path.cwd(),
        sub_agents=bundle.sub_agents,
        question=question,
        run_id=trace.dir.name,
        run_dir=str(trace.dir),
        model=model,
        max_turns=max_turns,
    )
    stop_reason = "max_turns"
    answer = ""

    _log_dir = trace.dir / "log" if debug_llm_io else None
    if _log_dir is not None:
        _log_dir.mkdir(exist_ok=True)

    use_responses_api = llm.is_openai_model(model)
    responses_session_id = uuid.uuid4().hex if use_responses_api else None
    llm_config = {
        "model": model,
        "api": "responses" if use_responses_api else "chat_completions",
        "reasoning_effort": llm.REASONING_EFFORT,
        "max_output_tokens": llm.MAX_TOKENS,
        "session_id": responses_session_id,
    }
    trace.event("llm_config", **llm_config)
    response_history: list = []
    responses_tools: list[dict] | None = None
    reasoning_cfg: dict | None = None
    resp_input: list = []
    if use_responses_api:
        responses_tools = llm.chat_tools_to_responses(bundle.tool_schemas)
        reasoning_cfg = (
            {"effort": llm.REASONING_EFFORT} if llm.REASONING_EFFORT else None
        )
        resp_input = [{"role": "user", "content": question}]
        trace.event("responses_api", model=model)

    # Chat Completions sends this message list directly. Responses keeps this
    # view for middleware and replays complete output items for model continuity.
    messages: list[dict] = [
        {"role": "system", "content": bundle.system_prompt},
        {"role": "user", "content": question},
    ]

    last_turn = 0
    for turn in range(1, max_turns + 1):
        last_turn = turn
        ctx._current_turn = turn
        ctx.current_turn_calls = []

        response_input = resp_input
        if use_responses_api:
            before_messages = copy.deepcopy(messages)
            for mw in bundle.middlewares:
                if mw.before_llm:
                    try:
                        messages = await mw.before_llm(messages, ctx)
                    except Exception as e:
                        trace.event(
                            "middleware_error",
                            hook="before_llm",
                            mw=mw.name,
                            error=str(e),
                        )
            additions = [
                x
                for m in _middleware_additions(before_messages, messages)
                if (x := _responses_input_from_middleware_message(m)) is not None
            ]
            if additions:
                response_input = resp_input + additions
        else:
            for mw in bundle.middlewares:
                if mw.before_llm:
                    try:
                        messages = await mw.before_llm(messages, ctx)
                    except Exception as e:
                        trace.event(
                            "middleware_error",
                            hook="before_llm",
                            mw=mw.name,
                            error=str(e),
                        )

        if _log_dir is not None:
            _req_log: dict[str, Any] = {"turn": turn, "model": model}
            if use_responses_api:
                _req_log["type"] = "responses"
                _req_log["input"] = response_history + response_input
                _req_log["continuation"] = "stateless"
                _req_log["session_id"] = responses_session_id
                _req_log["reasoning"] = reasoning_cfg
                _req_log["max_output_tokens"] = llm.MAX_TOKENS
            else:
                _req_log["type"] = "chat"
                _req_log["messages"] = messages
                _req_log["tools_count"] = (
                    len(bundle.tool_schemas) if bundle.tool_schemas else 0
                )
            _req_file = _log_dir / f"turn_{turn:03d}_request.json"
            trace.write_json(_req_file, _req_log)

        is_last_turn = turn == max_turns
        _tc = "none" if is_last_turn else "auto"
        _tools_resp = None if is_last_turn else responses_tools
        _tools_chat = None if is_last_turn else bundle.tool_schemas

        _llm_last_err: Exception | None = None
        for _attempt in range(1, llm.LLM_MAX_RETRIES + 1):
            try:
                request_started = time.monotonic()
                if use_responses_api:
                    resp = await llm.responses(
                        response_history + response_input,
                        model=model,
                        instructions=bundle.system_prompt,
                        tools=_tools_resp,
                        tool_choice=_tc,
                        reasoning=reasoning_cfg,
                        session_id=responses_session_id,
                    )
                else:
                    resp = await llm.chat(
                        messages, model=model, tools=_tools_chat, tool_choice=_tc
                    )

                if _log_dir is not None:
                    try:
                        _resp_data = (
                            resp.model_dump()
                            if hasattr(resp, "model_dump")
                            else repr(resp)
                        )
                    except Exception:
                        _resp_data = repr(resp)
                    _resp_file = _log_dir / f"turn_{turn:03d}_response.json"
                    trace.write_json(_resp_file, {"turn": turn, "response": _resp_data})
                _llm_last_err = None
                break  # success

            except Exception as e:
                _llm_last_err = e
                logger.warning(
                    "LLM call failed (turn %d, attempt %d/%d): %s",
                    turn,
                    _attempt,
                    llm.LLM_MAX_RETRIES,
                    trace.redact(str(e)),
                )
                if llm.is_fatal_api_error(e):
                    break
                if _attempt < llm.LLM_MAX_RETRIES:
                    await asyncio.sleep(2**_attempt)  # 2s, 4s

        if _llm_last_err is not None:
            e = _llm_last_err
            http_detail = {}
            for key in ("status_code", "llm_provider", "model"):
                val = getattr(e, key, None)
                if val is not None:
                    http_detail[key] = val
            cur = e
            while cur is not None:
                http_resp = getattr(cur, "response", None)
                if http_resp is not None and hasattr(http_resp, "status_code"):
                    http_detail["status"] = getattr(http_resp, "status_code", None)
                    http_detail["url"] = str(getattr(http_resp, "url", ""))
                    http_detail["headers"] = dict(getattr(http_resp, "headers", {}))
                    try:
                        http_detail["body"] = http_resp.text
                    except Exception:
                        http_detail["body"] = repr(getattr(http_resp, "content", b""))
                    break
                cur = getattr(cur, "original_exception", None) or getattr(
                    cur, "__cause__", None
                )
            logger.warning(
                "LLM call failed (attempts=%d, turn=%d): %s\nHTTP detail: %s",
                _attempt,
                turn,
                trace.redact(str(e)),
                trace.redact(json.dumps(http_detail, ensure_ascii=False, default=str)),
            )
            stop_reason = f"llm_error: {e}"
            break

        usage = {
            "role": "primary",
            "turn": turn,
            "model": model,
            "call_id": getattr(resp, "id", None),
            "latency_seconds": time.monotonic() - request_started,
            "usage": llm.usage_dict(resp),
        }
        ctx.model_usage.append(usage)
        trace.event("model_usage", **usage)
        failure = llm.response_error(resp, responses_api=use_responses_api)
        if failure:
            if use_responses_api:
                partial, _, _ = llm.extract_responses_output(resp)
                messages.append({"role": "assistant", "content": partial})
            elif resp.choices:
                messages.append(_serialize_assistant(resp.choices[0].message))
            stop_reason = f"llm_error: {failure}"
            trace.event("llm_error", turn=turn, error=failure)
            break

        if use_responses_api:
            response_history.extend(copy.deepcopy(response_input))
            response_history.extend(
                item.model_dump(mode="json", exclude_none=True)
                if hasattr(item, "model_dump")
                else copy.deepcopy(item)
                for item in (resp.output or [])
            )
            content, reasoning, function_calls = llm.extract_responses_output(resp)
            adapter = _ResponsesMiddlewareAdapter(
                resp, content, reasoning, function_calls
            )
            original_call_ids = set(adapter._original_call_ids)
            for mw in bundle.middlewares:
                if mw.after_llm:
                    try:
                        updated = await mw.after_llm(adapter, ctx)
                        adapter = _ensure_responses_adapter(
                            updated,
                            original_call_ids=original_call_ids,
                        )
                    except Exception as e:
                        trace.event(
                            "middleware_error",
                            hook="after_llm",
                            mw=mw.name,
                            error=str(e),
                        )
            adapter.sync_from_message()
            content = adapter.content or ""
            reasoning = adapter.reasoning_content or adapter.reasoning or ""
            tc_list = adapter.common_tool_calls()
        else:
            for mw in bundle.middlewares:
                if mw.after_llm:
                    try:
                        resp = await mw.after_llm(resp, ctx)
                    except Exception as e:
                        trace.event(
                            "middleware_error",
                            hook="after_llm",
                            mw=mw.name,
                            error=str(e),
                        )

            # Normalize response into common variables
            tc_list = []
            msg = resp.choices[0].message
            content = msg.content or ""
            reasoning = getattr(msg, "reasoning_content", None) or ""
            for tc in getattr(msg, "tool_calls", None) or []:
                tc_list.append(_chat_tool_call_to_common(tc))

        trace.event(
            "assistant",
            turn=turn,
            content=content,
            reasoning=reasoning,
            n_tool_calls=len(tc_list),
        )

        if not tc_list:
            if not content.strip():
                stop_reason = "llm_error: model returned no final answer text"
                break
            final_action, final_answer, feedback = await _run_before_final_hooks(
                content,
                ctx,
            )
            if final_action == "continue" and feedback:
                messages.append({"role": "assistant", "content": final_answer})
                messages.append({"role": "user", "content": feedback})
                if use_responses_api:
                    resp_input = [{"role": "user", "content": feedback}]
                continue

            check_action, final_answer, check_feedback = await _run_final_answer_check(
                final_answer,
                ctx,
                messages,
            )
            if check_action == "continue" and check_feedback:
                messages.append({"role": "assistant", "content": final_answer})
                messages.append({"role": "user", "content": check_feedback})
                if use_responses_api:
                    resp_input = [{"role": "user", "content": check_feedback}]
                continue

            messages.append({"role": "assistant", "content": final_answer})
            answer = final_answer
            stop_reason = "no_tool_calls"
            break

        if use_responses_api:
            messages.append(_middleware_assistant_message(content, tc_list))
        else:
            messages.append(_serialize_assistant(msg))

        tool_outputs: list[dict] = []
        injected_tool_messages: list[dict] = []
        for tc in tc_list:
            name = tc["name"]
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {}
            before_tool_seq = ctx._tool_seq
            try:
                result = await _dispatch(name, args, ctx)
            except Exception as e:
                result = f"tool error: {e}"
            result_metadata = {}
            if ctx.tool_history and ctx.tool_history[-1].seq > before_tool_seq:
                result_metadata = copy.deepcopy(ctx.tool_history[-1].result_metadata)
            trace.event(
                "tool_call",
                turn=turn,
                tool=name,
                args=args,
                result=result,
                result_metadata=result_metadata,
                search=ctx.search_calls,
                read=ctx.read_calls,
            )
            if use_responses_api:
                if not tc.get("injected"):
                    tool_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": tc["id"],
                            "output": result,
                        }
                    )
                else:
                    injected_tool_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Runtime middleware executed an additional tool call.\n"
                                f"Tool: {name}\n"
                                f"Arguments: {json.dumps(args, ensure_ascii=False)}\n"
                                f"Result:\n{result}"
                            ),
                        }
                    )
            else:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )
            if use_responses_api:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    }
                )

        if use_responses_api:
            resp_input = tool_outputs + injected_tool_messages

        # ── process pending injections from after_tool ──
        if ctx._pending_injections:
            inj = ctx._pending_injections[0]
            inj_name, inj_args = inj["name"], inj.get("args", {})
            ctx._in_injected_call = True
            before_tool_seq = ctx._tool_seq
            try:
                inj_result = await _dispatch(inj_name, inj_args, ctx)
            except Exception as e:
                inj_result = f"injected tool error: {e}"
                trace.event("injection_error", tool=inj_name, error=str(e))
            finally:
                ctx._in_injected_call = False
                ctx._pending_injections.clear()
            inj_metadata = {}
            if ctx.tool_history and ctx.tool_history[-1].seq > before_tool_seq:
                inj_metadata = copy.deepcopy(ctx.tool_history[-1].result_metadata)
            trace.event(
                "tool_call",
                turn=turn,
                tool=inj_name,
                args=inj_args,
                result=inj_result,
                injected=True,
                result_metadata=inj_metadata,
                search=ctx.search_calls,
                read=ctx.read_calls,
            )
            inj_msg = {
                "role": "user",
                "content": (
                    "Runtime middleware executed an additional tool call.\n"
                    f"Tool: {inj_name}\n"
                    f"Arguments: {json.dumps(inj_args, ensure_ascii=False)}\n"
                    f"Result:\n{inj_result}"
                ),
            }
            if use_responses_api:
                resp_input.append(inj_msg)
            else:
                messages.append(inj_msg)
            ctx._injections_count += 1

    # ------------------------------------------------------------------
    # Strip residual tool-call tokens (e.g. DeepSeek DSML markers)
    # ------------------------------------------------------------------
    def _clean_answer(text: str) -> str:
        return re.sub(
            r"<｜｜DSML｜｜tool_calls>.*?(?:</｜｜DSML｜｜tool_calls>|\Z)",
            "",
            text,
            flags=re.DOTALL,
        ).strip()

    answer = _clean_answer(answer)

    needs_forced_answer = not answer and not stop_reason.startswith("llm_error")

    # ------------------------------------------------------------------
    # Forced answer for non-normal exits
    # ------------------------------------------------------------------
    if needs_forced_answer:
        forced_prompt = (
            "You have used all available turns. No more tool calls are allowed. "
            "Do NOT output any tool-call markup or XML tags. "
            "Provide your best final answer to the original question now "
            "as plain text, citing source URLs inline. "
            "If the evidence you gathered is insufficient, give your best "
            "guess and explicitly note the uncertainty."
        )
        for _attempt in range(1, llm.LLM_MAX_RETRIES + 1):
            try:
                request_started = time.monotonic()
                if use_responses_api:
                    forced_input = (
                        response_history
                        + resp_input
                        + [{"role": "user", "content": forced_prompt}]
                    )
                    resp = await llm.responses(
                        forced_input,
                        model=model,
                        instructions=bundle.system_prompt,
                        tools=None,
                        tool_choice="none",
                        reasoning=reasoning_cfg,
                        session_id=responses_session_id,
                    )
                    forced_content, _, _ = llm.extract_responses_output(resp)
                else:
                    forced_messages = messages + [
                        {"role": "user", "content": forced_prompt}
                    ]
                    resp = await llm.chat(
                        forced_messages, model=model, tools=None, tool_choice="none"
                    )
                    forced_content = (
                        resp.choices[0].message.content if resp.choices else ""
                    )
                usage = {
                    "role": "forced_answer",
                    "turn": last_turn + 1,
                    "model": model,
                    "call_id": getattr(resp, "id", None),
                    "latency_seconds": time.monotonic() - request_started,
                    "usage": llm.usage_dict(resp),
                }
                ctx.model_usage.append(usage)
                trace.event("model_usage", **usage)
                forced = _clean_answer(forced_content or "")
                if forced:
                    # The forced path cannot loop back to the model, so keep only
                    # the finalized answer (the check itself falls back to accept
                    # when no turns remain).
                    _, forced, _ = await _run_final_answer_check(
                        forced, ctx, messages
                    )
                messages.extend(
                    [
                        {"role": "user", "content": forced_prompt},
                        {"role": "assistant", "content": forced},
                    ]
                )
                failure = llm.response_error(resp, responses_api=use_responses_api)
                if failure:
                    stop_reason = f"llm_error: {failure}"
                    trace.event("llm_error", turn=last_turn + 1, error=failure)
                    break
                if forced:
                    answer = forced
                trace.event(
                    "forced_answer", stop_reason=stop_reason, length=len(forced)
                )
                break
            except Exception as e:
                if llm.is_fatal_api_error(e):
                    break
                if _attempt < llm.LLM_MAX_RETRIES:
                    await asyncio.sleep(2**_attempt)

    if not answer:
        answer = "(no answer produced)"
        if not stop_reason.startswith("llm_error"):
            stop_reason = "llm_error: model returned no final answer text"

    if not stop_reason.startswith("llm_error"):
        stop_reason = "completed"

    trace.save_answer(answer)
    summary = {
        "question": question,
        "llm_config": llm_config,
        "stop_reason": stop_reason,
        "turns": last_turn,
        "search_calls": ctx.search_calls,
        "read_calls": ctx.read_calls,
        "run_dir": str(trace.dir),
        "workspace": str(bundle.root),
        "side_llm_calls": ctx._side_llm_calls,
        "unique_urls_searched": len(set(u for sr in ctx.searches for u in sr.urls)),
        "unique_urls_read": len(set(r.url for r in ctx.reads)),
        "read_failures": sum(1 for r in ctx.reads if not r.success),
        "tool_skips": ctx._tool_skips,
        "tool_redirects": ctx._tool_redirects,
        "injections_count": ctx._injections_count,
        "final_continues": ctx._final_continues,
        "usage": ctx.model_usage,
    }
    trace.save_summary(summary)
    trace.event("run_end", **summary)
    trace.close()

    return trace.redact({"answer": answer, "messages": messages, **summary})
