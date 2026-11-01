from __future__ import annotations


def _consume_ephemeral_reasoning_off(agent) -> bool:
    """Consume the one-shot "answer without thinking" continuation flag.

    Set by the length-continuation path when a request returned reasoning but NO
    visible content (thinking ate the output cap); continuation turns never replay
    prior reasoning, so thinking ON would re-burn the budget. When True the caller
    overrides the wire reasoning_config with ``{"enabled": False, "effort": "none"}``
    for exactly the next call. Prompt-cache cost is bounded to ONE cold prefix write
    on config-sensitive providers (Anthropic, OpenAI) — far cheaper than four futile
    full-budget continuations.
    """
    consumed = bool(getattr(agent, "_ephemeral_reasoning_off", False))
    if consumed:
        agent._ephemeral_reasoning_off = False
    return consumed


def _reasoning_config_for_wire(agent):
    """``agent.reasoning_config`` with the one-shot reasoning-off override applied.

    Once the route has answered a disable with "reasoning is mandatory"
    (``agent._reasoning_disable_rejected``), every disable — configured or
    the one-shot continuation override — is dropped for the rest of the
    session: the request goes out without a reasoning config and the route
    applies its own default.
    """
    cfg = agent.reasoning_config
    ephemeral_off = _consume_ephemeral_reasoning_off(agent)
    if getattr(agent, "_reasoning_effort_rejected", False):
        # The route rejected the configured reasoning LEVEL itself (#100536: ``reasoning.effort:
        # max`` on an enabled config). Omit the reasoning fields for the rest of the session —
        # the route default — as the auxiliary ladder does; resending would 400 identically.
        agent._wire_reasoning_config = None
        return None
    if cfg is None:
        # Unset effort: the profile's default (custom/OpenAI-compatible: medium) rather than the
        # route's own, recorded below as what went out so a rejection of it lands in the branch above.
        from .boundaries import unset_reasoning_default
        cfg = unset_reasoning_default(agent)
    if getattr(agent, "_reasoning_disable_rejected", False):
        # The route rejects disables. Resend exactly what the session has
        # been sending — the user's own config — so the retry lands on the
        # same provider cache key as every prior request. Only a config that
        # is itself a disable changes, and that session has never sent
        # anything else, so nothing warm is lost: a route that said the
        # disable is *mandatory-on* gets the floor effort (closest to what
        # the user asked for); a relay that does not know the field gets
        # nothing (route default).
        if isinstance(cfg, dict) and (
            cfg.get("enabled") is False or cfg.get("effort") == "none"
        ):
            if getattr(agent, "_reasoning_floor_required", False):
                from .boundaries import REASONING_FLOOR_EFFORT
                floored = {**cfg, "enabled": True, "effort": REASONING_FLOOR_EFFORT}
                agent._wire_reasoning_config = floored
                return floored
            agent._wire_reasoning_config = None
            return None
        agent._wire_reasoning_config = cfg
        return cfg
    if ephemeral_off:
        cfg = {**(cfg or {}), "enabled": False, "effort": "none"}
    # What actually went out: the reasoning-rejection rung reads it to tell a rejected
    # disable (drop the disable) from a rejected level (drop the reasoning fields).
    agent._wire_reasoning_config = cfg
    return cfg
