# Pi Python port baseline

This Python runtime ports the supported headless agent loop, built-in tools,
resource loading, and prompt text from [Pi](https://github.com/badlogic/pi-mono),
version **v1.4.0**, commit `4a080252f06caf63a525d7873c5d94d3c23887e0`.

The upstream source is distributed under the MIT license; its original notice
is preserved in [LICENSE](LICENSE). FlashRSI's adapter and framework remain
under the repository's Apache-2.0 license.

The Python port runs from the selected Agent Snapshot without Node.js, npm, or
the Pi CLI. Supported behavior and parity limits are documented in
`docs/agent-integration.md` in the FlashRSI repository. This is a partial semantic
port, and does not implement every upstream CLI, provider, or extension feature.

## Compaction and session port

The Snapshot contains the Python implementation of Pi's v3 append-only JSONL
session tree, context-edit projection, automatic threshold compaction, manual
`/compact [focus]`, one bounded compaction-and-retry recovery for context
overflow/recoverable length, and `/tree <entry-id> [focus]` branch summaries.
Summary generation is transactional: failure, incomplete generation, or
cancellation leaves the original transcript and selected branch intact. Raw
session entries are retained after successful compaction as well.

`session_file` explicitly enables persistence, with relative paths resolved from
the working directory; otherwise the session stays in memory. `session_leaf_id`
selects a saved branch, and `session_target_id` navigates before a normal prompt.
The nested aliases `session: {file, leaf_id}` are accepted.

`compaction` defaults to `enabled: true`, `reserveTokens: 16384`, and
`keepRecentTokens: 20000`. It accepts per-model `modelOverrides`; Snapshot
settings are merged first and explicit role settings take precedence.
`branch_summary` defaults to `enabled: true` and `reserveTokens: 16384`, with
`customInstructions`, `replaceInstructions`, and `label` controls. `retry`
defaults to `enabled: true`, `maxRetries: 3`, `baseDelayMs: 2000`, and
`maxAgentDelayMs: 60000`; nested `provider` controls `maxRetries`, `timeoutMs`,
and `maxRetryDelayMs`. Unknown nested options fail explicitly.

`context_window` and `model_max_tokens` can override the selected model limits.
The bundled `model_limits.json` contains the complete 1,599-model Pi AI
**1.4.0 release** catalog: limits, API selection, provider compatibility,
thinking maps, sampling defaults, prices, and headers.
The generated hydrated catalog is absent from the upstream Git checkout;
development tooling reads the matching release artifact to extract plain JSON.
Unknown models default to 128,000 context tokens and 16,384 output tokens.

The provider estimator uses upstream's UTF-16 character counts, 3.5 characters
per token, valid historical provider usage, and 4,096-token context margin. It
is intentionally distinct from the coding agent's characters/4 compaction
estimator. Normal Anthropic turns and summaries share output-cap and thinking
options: legacy token budgets, adaptive effort, managed effort markers, signed
and redacted thinking replay, and configured fallback models. Compaction uses
the selected thinking level only for reasoning models; branch summaries omit
it, as in the original source.

Summary requests use the caller's explicit role model, API key, base URL, and
custom headers. The three supported `llm.model_api` values are
`openai-completions`, `openai-responses`, and `anthropic-messages`; an explicit
API selects the actual request path. Unknown values fail before session writes.
No credentials are discovered from host environment variables or session files.
The adapter exposes `Pi.compact(...)` and `Pi.navigate_session(...)`; native
functions additionally accept `asyncio.Event` signals for summary cancellation
and full-run cancellation. Adapter timeouts preserve completed events and usage
while the same abort signal settles subprocesses and queued file operations.

## Main loop and providers

The default main loop ends naturally, without a hidden 64-turn limit. An
explicit positive `max_turns` is an optional FlashRSI execution bound. Agent
session retries preserve the failed assistant in raw history and hide it from
the next request with a `context_edit`; their budget and backoff are separate
from provider HTTP retries, whose upstream default is zero. HTTP retry status,
`x-should-retry`, Retry-After timing, delay limits, and cancellation are ported
from the original helper. Overflow recovery follows the compaction path.

The Anthropic request builder handles adaptive and budget thinking, managed
effort markers, signed/redacted reasoning replay, fallback models, strict tool
schemas, the one-time preferred-strict 400 downgrade, cache controls, native
system and tool updates, text/image content, and response usage/pricing.
Explicit API keys and explicit Anthropic OAuth tokens use their respective
upstream header/body formats; credential discovery and refresh remain outside
the headless adapter.

OpenAI Completions and Responses builders retain the original reasoning fields,
developer roles, output caps (including the Responses minimum of 16 tokens),
sampling defaults, model compatibility, strict/grammar tool declarations, and
native incremental tool announcements. Replay preserves opaque reasoning,
text signatures, namespaces, and paired call/item identifiers. Cross-model
transforms, orphan tool-result repair, image downgrade, and grouped Completions
tool-result images follow the source message conversions. Cache-read and
cache-write tokens are subtracted from OpenAI input once before pricing.
Provider-specific thinking templates, token budgets, routing, prompt caching,
session affinity headers, and returned Responses service-tier prices use the
ported compatibility helpers. Snapshot `thinkingBudgets` settings apply to
both the OpenAI and legacy Anthropic paths; role `thinking_budgets` or
`thinkingBudgets` overrides the Snapshot setting.

The transport consumes live SSE for all three supported APIs, retaining
incremental text, thinking/signatures, tool argument JSON and usage. It also
accepts complete JSON replies from compatible endpoints. Request-opening errors
use the provider retry policy; an interrupted stream finalizes its existing
partial message and never retries already consumed bytes. Explicit aborts save
the partial response and its usage to the session. Cancelling the Python task
itself propagates cancellation and closes the HTTP stream.

`Pi.run_with_controls(...)` accepts `on_event`, `steering_queue`,
`follow_up_queue`, `hooks`, and `cancel_event` without serializing Python
callables into role configuration or Snapshots. Native `PendingMessageQueue`
uses the original `one-at-a-time` or `all` drain modes. Hooks accept snake_case
or source camelCase names: `prepareRequest`, `prepareNextTurn`,
`transformContext`, `convertToLlm`, `getApiKey`, `finishTurn`, `beforeToolCall`,
`afterToolCall`, `getSteeringMessages`, and `getFollowUpMessages`. Hooks may be
synchronous or asynchronous. Tool preparation, blocking, result overrides,
early termination, live updates, and batch/transcript ordering use the source
boundaries; `structuredContent` stays on execution results as in the original
loop and is not added to persisted tool-result messages.

## Offline evidence and limits

The checked-in fixtures execute original pinned TypeScript, with fixed offline
model replies or intercepted request bodies. Compaction evidence covers 13
preparation/projection/summary paths, 11 branch-summary paths, four branch
collection paths, 16 summary-provider request scenarios, and eight provider
estimation/output-cap scenarios. The expanded provider fixtures cover 33
Anthropic request/response/fallback scenarios, 30 full OpenAI request bodies,
32 original HTTP retry-helper scenarios, and 122 tool-state/schema/grammar
assertions derived from original transcript and provider helpers. Another
31 actual provider scenarios supply 92 request/canonical-message/HTTP-boundary
checks for dynamic tools, grammar calls, refusal, truncation, and failure
responses. The compatibility-options oracle supplies 152 checks for thinking
formats/budgets, routing, caching, affinity headers, and service-tier pricing.
Another 113 integration checks carry these original expectations through the
native HTTP boundary, including complete cache-control bodies, header override
precedence, sampling precedence, service-tier costs, and saved Snapshot thinking
budgets for Anthropic and OpenAI.

Python integration tests additionally exercise the actual HTTP boundary,
automatic retries, more than 64 tool turns, all three summary APIs, caller
credentials, saved-session resume, encrypted reasoning replay, cached usage,
timeout retention, and cancellation during HTTP, retry sleeps, Bash descendant
execution, and queued file writes. Two recovered cancellation races are covered:
cancel takes priority at `max_turns`, and an already successful retry is not
finished a second time when a later request is cancelled.

Incremental provider fixtures capture synchronous original `stream.push`
snapshots for 60 OpenAI and 33 Anthropic scenarios, plus 30 original partial-JSON
repair/final-validation cases. Native HTTP integration covers SSE framing,
split UTF-8, live async observers, terminal errors before EOF, partial text/tool
aborts, persisted partial usage, external task cancellation, retries, and
three-provider tool replay. A separate 30-scenario original `runAgentLoop`
oracle supplies 93 checks for queue modes, hook boundaries, continuation/end
decisions, context/model/thinking changes and actual source SSE observer
snapshots. Provider push snapshots and agent observer snapshots are checked
separately: events emitted within one decoded SSE frame share the source's
completed partial before the agent consumes them.

Regenerate from a checkout at the commit above and matching Pi AI dependencies:

```sh
export PI_REFERENCE_SOURCE=/path/to/pi-mono
export PI_REFERENCE_DEPS=/path/to/matching/node_modules
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_compaction_upstream.mjs \
  > tests/fixtures/pi_compaction_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_branch_summary_upstream.mjs \
  > tests/fixtures/pi_branch_summary_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_summary_options_upstream.mjs \
  > tests/fixtures/pi_summary_options_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_anthropic_upstream.mjs \
  > tests/fixtures/pi_anthropic_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_openai_provider_upstream.mjs \
  > tests/fixtures/pi_openai_provider_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_openai_tools_upstream.mjs \
  > tests/fixtures/pi_openai_tools_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_openai_dynamic_upstream.mjs \
  > tests/fixtures/pi_openai_dynamic_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_openai_options_upstream.mjs \
  > tests/fixtures/pi_openai_options_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_provider_retry_upstream.mjs \
  > tests/fixtures/pi_provider_retry_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_openai_stream_upstream.mjs \
  > tests/fixtures/pi_openai_stream_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_anthropic_stream_upstream.mjs \
  > tests/fixtures/pi_anthropic_stream_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_loop_controls_upstream.mjs \
  > tests/fixtures/pi_loop_controls_upstream.json
node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
  ./tests/fixtures/generate_pi_compaction_upstream.mjs --model-limits \
  > flashrsi/agents/pi_agent/runtime/pi_native/model_limits.json
```

Node 24 type stripping and these development dependencies are used only to
regenerate offline evidence. Production Snapshot execution uses Python and
`httpx`, PyYAML, Pillow, NumPy and the declared Rust-regex Python binding; it
does not execute Node, npm, a Pi package, or a Pi CLI subprocess. OAuth credential
discovery/refresh, provider federation, interactive UI, TypeScript extension
loading, and provider APIs outside the three documented routes remain outside
this headless adapter. The callable Python hook boundary covers native headless
extensions. Fixed-response parity establishes the tested harness behavior;
it does not establish equal live-model answers or benchmark accuracy.


## Prompt resources and tool boundaries

`prompt_builder.py`, `tool_manifest.json` and `PROMPT_SOURCES.json` preserve the
original structured prompt sections, built-in tool contributions and provenance.
The 185 files under `reference/` are pinned read-only documentation/examples
referenced by the original default prompt. Some are TS/JS/WASM/package metadata;
they are data and are never loaded as a Node runtime or npm dependency.
Original-source fixtures cover prompt construction/section deltas, YAML core
frontmatter, skill discovery/ignore, tool preparation and execution. The runtime
uses PyYAML and Pillow alongside httpx; container staging declares these.

Small image attachments retain original bytes. The image and Rust-regex helpers
have their own pinned-source fixtures. Fixture coverage is finite; unsupported
interactive and provider-specific surfaces are not inferred to have parity.
The repository's `runs/full-parity-audit-20261101/REPORT.md` records the original
audit; the executable fixtures and tests above describe the current port.
