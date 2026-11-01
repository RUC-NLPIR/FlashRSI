from __future__ import annotations
from typing import Any

def _model_dump_safe(obj):
    """``model_dump(warnings=False)`` (avoids pydantic serializer UserWarnings on
    generic-union SDK models), falling back for shims that reject the kwarg."""
    try:
        return obj.model_dump(warnings=False)
    except TypeError:
        return obj.model_dump()


def _dump_if_model(value):
    return _model_dump_safe(value) if hasattr(value, "model_dump") else value


def _assistant_tool_call_dict(agent, tool_call, index: int) -> dict:
    raw_id = getattr(tool_call, "id", None)
    call_id = getattr(tool_call, "call_id", None)
    if not isinstance(call_id, str) or not call_id.strip():
        call_id, _ = agent._split_responses_tool_id(raw_id)
    if not isinstance(call_id, str) or not call_id.strip():
        if isinstance(raw_id, str) and raw_id.strip():
            call_id = raw_id.strip()
        else:
            _fn = getattr(tool_call, "function", None)
            call_id = agent._deterministic_call_id(getattr(_fn, "name", "") if _fn else "",
                getattr(_fn, "arguments", "{}") if _fn else "{}", index)
    call_id = call_id.strip()

    response_item_id = getattr(tool_call, "response_item_id", None)
    if not isinstance(response_item_id, str) or not response_item_id.strip():
        _, response_item_id = agent._split_responses_tool_id(raw_id)
    response_item_id = agent._derive_responses_function_call_id(call_id,
        response_item_id if isinstance(response_item_id, str) else None)
    # Arguments are deliberately NOT redacted: this dict is replayed to the model every
    # turn, so a ``***`` mask would break credential-dependent commands (#43083).
    tc_dict = {"id": call_id, "call_id": call_id, "response_item_id": response_item_id,
        "type": tool_call.type,
        "function": {"name": tool_call.function.name, "arguments": tool_call.function.arguments}}
    # Preserve extra_content (Gemini thought_signature) or Gemini 3 thinking
    # models 400 on the next request.
    # Tool-call arguments are intentionally NOT redacted here. This dict enters the in-memory conversation
    # history that is replayed to the model on every subsequent turn AND persisted to state.db, which is
    # itself replayed verbatim on session resume (get_messages_as_conversation). Masking a credential to
    # `***` here poisons that replay: the model reads back its own `PGPASSWORD='***' psql ...` call and
    # copies the placeholder into the next tool call, breaking every credential-dependent command on the
    # second turn (#43083). The masking also provided no real protection — the same secret still leaks
    # verbatim through tool OUTPUT (file contents, command output, diffs, the compaction block), none of
    # which this pass ever touched. Keeping secrets out of the replayable store is a separate
    # tokenization/vault concern, not something arg-redaction can deliver without breaking replay.
    # Storage-time redaction remains governed by the `security.redact_secrets` toggle. (#19798 introduced
    # this; #43083 removed it.) Preserve extra_content (e.g. Gemini thought_signature) so it is sent back on
    # subsequent API calls. Without this, Gemini 3 thinking models reject the request with a 400 error.
    extra = getattr(tool_call, "extra_content", None)
    if extra is not None:
        tc_dict["extra_content"] = _dump_if_model(extra)
    # Copilot's Gemini 3 variant signs the call inside ``function`` (replayed only to Copilot).
    from .reasoning_carriers import field
    fn_sig = field(tool_call, "thought_signature") or getattr(tool_call.function, "thought_signature", None)
    if isinstance(fn_sig, str) and fn_sig:
        tc_dict["function"]["thought_signature"] = fn_sig
    return tc_dict
