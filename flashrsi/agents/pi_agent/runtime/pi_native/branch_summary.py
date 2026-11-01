"""Pi v1.4.0 branch summaries and transactional session-tree navigation.

Ports ``branch-summarization.ts`` and the summary-related part of
``AgentSession.navigateTree``. Model requests are supplied by the Snapshot loop;
this module never discovers host credentials or runs the Pi CLI.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Awaitable, Callable, Mapping

from .compaction import (
    SUMMARIZATION_SYSTEM_PROMPT,
    content_text,
    estimate_tokens,
    file_operations,
    format_file_operations,
    is_retryable_summary_error,
    serialize_conversation,
)
from .session import Session, entry_messages, milliseconds, session_path

SummaryCall = Callable[[list[dict[str, Any]], int], Awaitable[dict[str, Any]]]

BRANCH_SUMMARY_PREAMBLE = (
    "The user explored a different conversation branch before returning here.\n"
    "Summary of that exploration:\n\n"
)

BRANCH_SUMMARY_PROMPT = """Create a structured summary of this conversation branch for context when returning later.

Use this EXACT format:

## Goal
[What was the user trying to accomplish in this branch?]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Work that was started but not finished]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [What should happen next to continue this work]

Keep each section concise. Preserve exact file paths, function names, and error messages."""


def collect_entries_for_branch_summary(
    session: Session, old_leaf_id: str | None, target_id: str
) -> dict[str, Any]:
    """Collect the old branch back to the deepest common ancestor."""
    if not old_leaf_id:
        return {"entries": [], "commonAncestorId": None}
    old_ids = {e["id"] for e in session_path(session.entries, old_leaf_id)}
    target_path = session_path(session.entries, target_id)
    common = next((e["id"] for e in reversed(target_path) if e["id"] in old_ids), None)
    by_id = {e["id"]: e for e in session.entries}
    entries = []
    current = old_leaf_id
    seen = set()
    while current and current != common:
        if current in seen:
            raise ValueError("Pi session contains a parent cycle")
        seen.add(current)
        entry = by_id.get(current)
        if entry is None:
            break
        entries.append(copy.deepcopy(entry))
        current = entry.get("parentId")
    return {"entries": list(reversed(entries)), "commonAncestorId": common}


def _message_from_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    kind = entry.get("type")
    if kind == "message":
        message = entry.get("message", {})
        # Upstream deliberately omits tool result bodies in branch summaries.
        return None if message.get("role") == "toolResult" else copy.deepcopy(message)
    if kind == "branch_summary":
        # Branch preparation includes even an empty checkpoint, whereas normal
        # session projection elides empty branch summaries.
        return {
            "role": "branchSummary",
            "summary": entry.get("summary", ""),
            "fromId": entry.get("fromId"),
            "timestamp": milliseconds(entry.get("timestamp")),
        }
    if kind in {"custom_message", "compaction"}:
        messages = entry_messages(entry)
        # A compaction's replayed system message is not branch conversation.
        return messages[-1] if messages else None
    return None


def prepare_branch_entries(
    entries: list[dict[str, Any]], token_budget: int = 0
) -> dict[str, Any]:
    """Keep the most recent branch messages, preserving important checkpoints."""
    details: dict[str, Any] = {"readFiles": [], "modifiedFiles": []}
    reads, modified = set(), set()
    for entry in entries:
        if (
            entry.get("type") == "branch_summary"
            and not entry.get("fromHook")
            and isinstance(entry.get("details"), Mapping)
        ):
            value = entry["details"]
            if isinstance(value.get("readFiles"), list):
                reads.update(value["readFiles"])
            if isinstance(value.get("modifiedFiles"), list):
                modified.update(value["modifiedFiles"])
    details.update(readFiles=sorted(reads), modifiedFiles=sorted(modified))
    messages: list[dict[str, Any]] = []
    total = 0
    for entry in reversed(entries):
        message = _message_from_entry(entry)
        if message is None:
            continue
        # File operations are collected before the budget check, as upstream.
        details = file_operations([message], details)
        tokens = estimate_tokens(message)
        if token_budget > 0 and total + tokens > token_budget:
            if entry.get("type") in {"compaction", "branch_summary"}:
                if total < token_budget * 0.9:
                    messages.insert(0, message)
                    total += tokens
            break
        messages.insert(0, message)
        total += tokens
    return {"messages": messages, "fileOps": details, "totalTokens": total}


async def _complete_summary(
    summarize: SummaryCall,
    conversation: list[dict[str, Any]],
    model_max_tokens: int,
    retry_policy: Mapping[str, Any] | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    policy = retry_policy or {}
    attempts = policy.get("maxRetries", 0) if policy.get("enabled") else 0
    retried = False
    try:
        for attempt in range(attempts + 1):
            try:
                response = await summarize(conversation, model_max_tokens)
            except Exception as exc:
                response = {
                    "stopReason": "error",
                    "errorMessage": str(exc),
                    "content": [],
                }
            error = str(response.get("errorMessage") or "")
            if (
                response.get("stopReason") != "error"
                or attempt >= attempts
                or not is_retryable_summary_error(error)
            ):
                return response
            delay = min(
                policy.get("baseDelayMs", 2000) * 2**attempt,
                policy.get("maxAgentDelayMs", 60000),
            )
            retried = True
            events.append(
                {
                    "type": "summarization_retry_scheduled",
                    "attempt": attempt + 1,
                    "maxAttempts": attempts,
                    "delayMs": delay,
                    "errorMessage": error or "Unknown error",
                }
            )
            await asyncio.sleep(delay / 1000)
            events.append(
                {"type": "summarization_retry_attempt_start", "source": "branchSummary"}
            )
    finally:
        if retried:
            events.append({"type": "summarization_retry_finished"})


async def generate_branch_summary(
    entries: list[dict[str, Any]],
    summarize: SummaryCall,
    *,
    context_window: int = 128000,
    model_max_tokens: int = 16384,
    reserve_tokens: int = 16384,
    custom_instructions: str | None = None,
    replace_instructions: bool = False,
    cancel_event: asyncio.Event | None = None,
    retry_policy: Mapping[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a branch checkpoint without mutating the session."""
    prepared = prepare_branch_entries(
        entries, (context_window or 128000) - reserve_tokens
    )
    if not prepared["messages"]:
        return {"summary": "No content to summarize"}
    instructions = BRANCH_SUMMARY_PROMPT
    if custom_instructions:
        instructions = (
            custom_instructions
            if replace_instructions
            else f"{instructions}\n\nAdditional focus: {custom_instructions}"
        )
    prompt = (
        "<conversation>\n"
        + serialize_conversation(prepared["messages"])
        + "\n</conversation>\n\n"
        + instructions
    )
    conversation = [
        {"role": "system", "content": SUMMARIZATION_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    if cancel_event is not None and cancel_event.is_set():
        return {"aborted": True}
    sink = events if events is not None else []
    task = asyncio.create_task(
        _complete_summary(summarize, conversation, model_max_tokens, retry_policy, sink)
    )
    cancelled = (
        asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
    )
    try:
        if cancelled is None:
            response = await task
        else:
            done, _ = await asyncio.wait(
                (task, cancelled), return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done and cancel_event.is_set():
                return {"aborted": True}
            response = await task
    finally:
        task.cancel()
        if cancelled is not None:
            cancelled.cancel()
        await asyncio.gather(
            task,
            *([cancelled] if cancelled is not None else []),
            return_exceptions=True,
        )
    if cancel_event is not None and cancel_event.is_set():
        return {"aborted": True}
    reason = response.get("stopReason")
    if reason == "aborted":
        return {"aborted": True}
    if reason == "error":
        return {
            "error": "Branch summarization failed: "
            + (response.get("errorMessage") or "Unknown error")
        }
    if reason == "length":
        return {
            "error": "Branch summarization failed: generation hit the token cap and the summary is incomplete"
        }
    if any(block.get("type") == "toolCall" for block in response.get("content", [])):
        return {"error": "Branch summarization attempted to call a tool"}
    details = prepared["fileOps"]
    summary = BRANCH_SUMMARY_PREAMBLE + content_text(response.get("content", []))
    summary += format_file_operations(details)
    return {
        "summary": summary or "No summary generated",
        "usage": response.get("usage", {}),
        **details,
    }


async def navigate(
    session: Session,
    target_id: str,
    summarize: SummaryCall,
    *,
    summarize_branch: bool = True,
    context_window: int = 128000,
    model_max_tokens: int = 16384,
    reserve_tokens: int = 16384,
    custom_instructions: str | None = None,
    replace_instructions: bool = False,
    label: str | None = None,
    cancel_event: asyncio.Event | None = None,
    retry_policy: Mapping[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Navigate to a persisted tree node, committing its summary only on success.

    Selecting a user/custom message returns its text for resubmission and places
    the new branch at that message's parent, matching Pi's tree editor behavior.
    Summary errors raise; an explicit cancel event returns a cancelled result.
    """
    old_leaf = session.leaf_id
    if target_id == old_leaf:
        return {"cancelled": False}
    target = next((e for e in session.entries if e.get("id") == target_id), None)
    if target is None:
        raise ValueError(f"Entry {target_id} not found")
    collected = collect_entries_for_branch_summary(session, old_leaf, target_id)
    summary = None
    if summarize_branch and collected["entries"]:
        summary = await generate_branch_summary(
            collected["entries"],
            summarize,
            context_window=context_window,
            model_max_tokens=model_max_tokens,
            reserve_tokens=reserve_tokens,
            custom_instructions=custom_instructions,
            replace_instructions=replace_instructions,
            cancel_event=cancel_event,
            retry_policy=retry_policy,
            events=events,
        )
        if summary.get("aborted"):
            return {"cancelled": True, "aborted": True}
        if summary.get("error"):
            raise RuntimeError(summary["error"])
    if cancel_event is not None and cancel_event.is_set():
        return {"cancelled": True, "aborted": True}
    user_target = (
        target.get("type") == "message"
        and target.get("message", {}).get("role") == "user"
    )
    custom_target = target.get("type") == "custom_message"
    new_leaf = target.get("parentId") if user_target or custom_target else target_id
    result: dict[str, Any] = {"cancelled": False}
    if user_target or custom_target:
        content = (
            target.get("content", [])
            if custom_target
            else target["message"].get("content", [])
        )
        result["editorText"] = content_text(content, "")
    session.leaf_id = new_leaf
    try:
        if summary and summary.get("summary"):
            details = {
                "readFiles": summary.get("readFiles", []),
                "modifiedFiles": summary.get("modifiedFiles", []),
            }
            entry = session.append(
                "branch_summary",
                fromId=old_leaf,
                summary=summary["summary"],
                details=details,
                **({"usage": summary["usage"]} if "usage" in summary else {}),
            )
            result["summaryEntry"] = entry
            if label:
                session.append("label", targetId=entry["id"], label=label)
        elif label:
            session.append("label", targetId=target_id, label=label)
    except BaseException:
        session.leaf_id = old_leaf
        raise
    return result


__all__ = [
    "collect_entries_for_branch_summary",
    "prepare_branch_entries",
    "generate_branch_summary",
    "navigate",
]
