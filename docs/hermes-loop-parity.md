# Hermes conversation-loop audit

Baseline: NousResearch/hermes-agent **v0.22.5**, commit
`bf0203a794a07aac3ff764972ab9087baa4e4f4e`.

The snapshot executes Python and sends HTTP using httpx. It does not import an
installed Hermes package, invoke Node/npm, use an OpenAI SDK, or discover host
Hermes profiles and credentials. Provider routes and credentials must be supplied
explicitly. This is a bounded headless snapshot, not complete Hermes product or
all-provider behavioral equivalence.

## Evidence

`tests/fixtures/generate_hermes_trajectory_upstream.py` executes the clean pinned
original `AIAgent.run_conversation` and its original forwarded modules, with fixed
SDK replies and tool-dispatch results. No original loop or policy helper is
replaced. Tool discovery/dispatch, provider-client construction, persistence and
cleanup are fixture boundaries. A virtual clock advances original retry waits.
The fixture retains original requests, outcomes, dependency versions, source
hashes and a hash of the generator.

`tests/test_hermes_trajectory_parity.py` replays the same inputs as HTTP responses
against the native snapshot and compares **65 complete trajectories (61 Chat/recovery + 4 Anthropic Messages)**: final text,
completion/failure/partial flags, logical API counts, usage, messages, tool-call
identity/arguments, dispatch counts, and semantic provider requests. Operational
timestamps, generated IDs, persistence metadata and provider defaults are excluded;
the independent Chat transport oracle tests cover request defaults and protocol
normalization. The loop fixture uses fixed tool results; independent original-source
tool tests cover actual tool behavior. These are deterministic policy tests, not
live-model quality or live-provider integration tests.

## Implemented loop paths

| Area | Implementation and evidence |
| --- | --- |
| Iteration budget | Original `IterationBudget`; provider retries do not consume model/tool iterations. Tool rounds, invalid names/JSON, duplicate calls, truncation and iteration summaries have original full-loop cases. |
| HTTP retry/recovery | Pinned original classifier, Retry-After parsing/caps, jitter, ZAI overload timing, bounded recovery ladder, eager explicit fallbacks and fresh transport recovery. HTTP-500/429, malformed-200, fallback auth/rate/format, recovery ladder and transport recovery run through the actual original loop. |
| Text stop gates | Original trailing-intent, ACK and degenerate guards, bounded shared continuation count and repetition checks. Optional product-specific verification/plugin gates are excluded below. |
| Empty replies | Original thinking-prefill and retry budget/deterministic-empty guard, post-tool nudge, housekeeping-only prior-content reuse, stale marker removal and explicit fallback. Pricing is unavailable and follows the original unknown-price fail-open path. |
| Reasoning | Original live-route trusted `answer_in_reasoning` policy using explicit custom-provider configuration; promoted text stays in `api_content` and reasoning sidecars. Private/signed reasoning remains private. Trusted final and stalled-plan promotion have full original-loop cases. |
| Refusal | HTTP-200 `content_filter` tries explicit fallback, then returns the original refusal copy and typed nonretryable `content_policy_blocked` result without appending the refused model row or charging its usage. Text, reasoning-only and no-explanation cases run through the original loop. |
| Responses | Original native response/continuation/compaction helpers; checkpoint, reasoning sidecars, call IDs, incomplete output and native-compaction rejection have dedicated original-source and real-HTTP tests. |
| Persistence | Explicit atomic JSON session with locking, original ephemeral-scaffold filter, interrupted-call pairing, stable runtime timestamp and context state. This storage boundary replaces the product SQLite/session stack. |
| Protocol boundary | Chat Completions, Responses and native Anthropic Messages. Anthropic text/tool/refusal, ordered signed thinking blocks, SSE/JSON decoding, OAuth/API-key headers, stream opt-out and explicit fallback are covered by four original-loop trajectories and HTTP tests. Native Gemini/Bedrock remain outside this snapshot; unsupported fallbacks are skipped with a diagnostic. |

Role-level `api_max_retries`, `auto_recovery_cycles`, `stall_guards`,
`intent_ack_continuation`, and `empty_response_guard` override the snapshot
configuration's original `agent` section. The framework reserves a role-level
`agent` key, so role configuration must use these top-level names.

## Remaining differences: product-only surfaces

The core request, recovery, tool-loop and session paths above are implemented from the pinned source. The remaining boundaries require services that a headless snapshot intentionally does not own:

| Original source | Snapshot boundary |
| --- | --- |
| Credential pool and provider discovery modules | Credentials, OAuth refresh, entitlement discovery, welcome-tier repair, pool rotation and restoration are disabled. Routes and fallbacks require explicit endpoint, provider, model and key configuration. |
| Product session/gateway modules | SQLite persistence, multi-process gateway delivery, historical replay expiry and UI/stream preview callbacks are replaced by explicit atomic JSON session files and buffered HTTP responses. |
| Optional plugin/product stop gates | Verifier, kanban/LSP, plugin transforms/hooks and product UI delivery are excluded. |
| Native Gemini and Bedrock protocols | OpenAI-compatible Gemini routes work through Chat; native Gemini and Bedrock SDK transports remain unsupported. |

`tool_search` reserved-name handling is **not** a missing reactive recovery rung.
The original Chat transport aliases it proactively for xAI in
`_rename_tool_search_bridge_for_xai` and reverses request-local aliases when
normalizing calls; the vendored Chat transport owns that behavior.

The source selections and import adaptations are recorded in
`upstream_loop/PROVENANCE.json` and `upstream_recovery/PROVENANCE.json`. Their
per-file snapshot hashes describe the exact frozen bytes used by this audit.
Changes to protocol profiles, request builders or loop recovery require new cases
before expanding the supported parity claim.
