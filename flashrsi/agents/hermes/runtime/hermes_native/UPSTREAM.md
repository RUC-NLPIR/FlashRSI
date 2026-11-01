# Hermes Python baseline

Source: https://github.com/NousResearch/hermes-agent

Baseline: v0.22.5, commit `bf0203a794a07aac3ff764972ab9087baa4e4f4e`.
Upstream's original MIT notice is preserved in [LICENSE](LICENSE).

This Snapshot contains the Python implementation of the supported headless,
OpenAI-compatible conversation path. Pure upstream helpers and prompt text are
retained where possible; the loop and local tool dispatch adapt those semantics
to FlashRSI's explicit role configuration and task workspace. No installed
Hermes CLI, npm package, or host Hermes profile is used.

The Snapshot includes full, proactive prune, micro, idle and manual context
compression; overflow/output-budget recovery; explicit persistent sessions with
pre-compression checkpoints and history search; and Responses native-compaction
policy, checkpoint replay and incomplete-response continuation. Chat Completions,
Responses and Anthropic Messages use plain HTTP with explicit role credentials.
Official Codex Responses SSE is decoded locally, without an SDK or CLI process. Compression
sources, Responses sources and continuation extractions have separate hash
manifests beside the runtime. The default iteration budget follows the upstream
`AIAgent` constructor's unlimited setting; roles can set `max_iterations`.

See `docs/agent-integration.md` in the FlashRSI repository for supported tools,
verification scope, and feature boundaries. This is a semantic subset of the
upstream product, not a complete CLI/gateway/provider implementation.


## Additional loop, transport and resource audit

`upstream_loop/` contains pinned original loop policy helpers. Fixed-response
fixtures exercise original `AIAgent.run_conversation`, including ordinary API
retries without consuming model iterations, empty-response guards, length
continuations, repetition/stall/ack guards and iteration-budget summaries.
`upstream_chat/` contains the original Chat transport, reasoning/schema/replay
helpers and selected bundled provider profiles with per-file provenance.
The HTTP boundary uses these helpers without constructing an upstream SDK.
Catalog capability snapshots and cache scopes are explicit inputs; plugin
registry discovery and live catalog warming are not implemented.

Resource tests execute the actual original runtime-context functions with fixed
host facts. Scratch paths are real and exposed to foreground commands, but the
upstream retention/process/worktree service is absent; the prompt omits its
24-hour pruning promise. IPYNB/DOCX/XLSX/SQLite readers use extracted original
stdlib functions (`DOCUMENT_SOURCES.json`). Optional PDF/OCR/anydoc and the
vision tool are absent.

The full audit found remaining search result ordering/pagination and Rust versus
Python regex differences. Foreground terminal and local tools do not imply
support for background/PTY tasks, process notifications, plugins, MCP, delegated
agents, browser/web/video/code tools or the original persistent-memory ecosystem.
Native Anthropic Messages is supported through the Snapshot transport; native
Bedrock/Gemini REST transports, live provider-catalog warming and host plugin
discovery remain outside this headless boundary. The original Chat recovery
policies for rejected reasoning (drop/floor), schema/grammar repair, image
downgrade and selected credit/header failures are retained in the Snapshot and
covered by the fixed-response and HTTP parity cases. This is a restricted
headless port; passing those cases is not proof of complete product equivalence
or equal live-model benchmark accuracy.
