from __future__ import annotations
from typing import Any
GUARDRAIL_ACTION_FIELD = "amazon-bedrock-guardrailAction"


def anthropic_response_guardrail_intervened(response: Any) -> bool:
    """True when Bedrock substituted the InvokeModel reply with guardrail messaging. Unlike Converse
    (``stopReason=guardrail_intervened``), InvokeModel keeps ``stop_reason=end_turn`` and signals the
    block only via an unmodelled body field the Anthropic SDK keeps in ``model_extra``."""
    extra = getattr(response, "model_extra", None) or {}
    return str(extra.get(GUARDRAIL_ACTION_FIELD, "")).upper() == "INTERVENED"

