/** Actual pinned Pi Anthropic provider, offline SSE fetch. See UPSTREAM.md. */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";
const root = process.env.PI_REFERENCE_SOURCE;
const deps = process.env.PI_REFERENCE_DEPS;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim() !== commit) throw new Error("Wrong source revision");
const pkg = path.join(deps, "@earendil-works/pi-ai");
if (JSON.parse(readFileSync(path.join(pkg, "package.json"))).version !== "1.4.0") throw new Error("Wrong model catalog release");
const { MODELS } = await import(pathToFileURL(path.join(pkg, "dist/models.generated.js")).href);
const { streamSimple } = await import(pathToFileURL(path.join(root, "packages/ai/src/api/anthropic-messages.ts")).href);
const zero = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const t = text => ({ type: "text", text });
const u = (content, timestamp = 1) => ({ role: "user", content, timestamp });
const tool = (name, description = name, extra = {}) => ({ name, description, parameters: { type: "object", properties: { path: { type: "string" }, limit: { type: "number" } }, required: ["path"] }, ...extra });
const read = tool("read"); const write = tool("write");
const system = (extra = {}) => ({ role: "system", content: "base prompt", toolsAdded: [read], timestamp: 0, ...extra });
const a = (content, extra = {}) => ({ role: "assistant", provider: "anthropic", model: "claude-fable-5-1", api: "anthropic-messages", content, stopReason: "stop", usage: zero, timestamp: 2, ...extra });
const call = { type: "toolCall", id: "call", name: "read", arguments: { path: "a.py" } };
const result = (extra = {}) => ({ role: "toolResult", toolCallId: "call", toolName: "read", content: [t("result")], isError: false, timestamp: 3, ...extra });
const image = { type: "image", mimeType: "image/png", data: "cGl4ZWw=" };
const base = [system(), u("hello")];
const inputs = [
  { name: "legacy_default_cache", id: "claude-sonnet-4-5", messages: base },
  { name: "legacy_collapses_sections_and_tool_deltas", id: "claude-sonnet-4-5", messages: [system({ sections: { goal: "old", remove: "gone" } }), u("hello"), a([t("prior")]), { role: "system", content: "later", sections: { goal: "new", remove: null }, toolsRemoved: [{ name: "read" }], toolsAdded: [write], timestamp: 4 }, u("next", 5)] },
  { name: "native_tool_changes_after_results", id: "claude-fable-5-1", reasoning: "medium", messages: [system({ sections: { goal: "old" } }), u("read"), a([call], { stopReason: "toolUse", providerThinkingLevel: "low" }), { role: "system", content: "later", sections: { goal: "new", absent: null }, toolsRemoved: [{ name: "read" }], toolsAdded: [write], timestamp: 4 }, result(), u("continue", 5)] },
  { name: "native_redefinition_omits_removal", id: "claude-opus-4-8", messages: [system(), u("read"), a([call], { model: "claude-opus-4-8", stopReason: "toolUse" }), result(), { role: "system", content: "", toolsRemoved: [{ name: "read" }], toolsAdded: [tool("read", "new read")], timestamp: 4 }, u("next", 5)] },
  { name: "native_system_without_initial_tools", id: "claude-fable-5-1", messages: [system({ toolsAdded: [] }), u("first"), { role: "system", content: "", sections: { mode: "strict" }, toolsAdded: [read], timestamp: 4 }, a([t("prior")], { providerThinkingLevel: "max" }), u("next", 5)] },
  { name: "summary_cache_none", id: "claude-fable-5-1", cacheRetention: "none", messages: base },
  { name: "long_cache", id: "claude-sonnet-4-5", cacheRetention: "long", messages: base },
  { name: "long_cache_unsupported", id: "fixture-no-long-cache", catalogId: "claude-sonnet-4-5", overrides: { compat: { supportsLongCacheRetention: false } }, cacheRetention: "long", messages: base },
  { name: "system_array_content", id: "claude-sonnet-4-5", messages: [system({ content: [t("one"), t("two")], sections: { goal: "three" } }), u("hello")] },
  { name: "nonvision_downgrade", id: "fixture-nonvision", catalogId: "claude-sonnet-4-5", overrides: { input: ["text"] }, messages: [system(), u([image, image]), a([call]), result({ content: [image, image] }), u("next")] },
  { name: "signed_thinking_and_orphan_repair", id: "claude-fable-5-1", messages: [system(), u("hello"), a([{ type: "thinking", thinking: "reason", thinkingSignature: "sig" }, call], { stopReason: "toolUse", providerThinkingLevel: "xhigh" }), u("interrupted", 4)] },
  { name: "cross_model_thinking_and_ids", id: "claude-sonnet-4-5", messages: [system(), u("hello"), a([{ type: "thinking", thinking: "private", thinkingSignature: "sig" }, { ...call, id: "a|b" }], { provider: "openai", api: "openai-responses", model: "gpt-5", stopReason: "toolUse" }), result({ toolCallId: "a|b" }), u("continue")] },
  { name: "error_images_and_empty_content", id: "claude-sonnet-4-5", messages: [system(), u([]), a([call]), result({ isError: true, content: [image, image, t("error"), image] }), u("next")] },
  { name: "eager_streaming_disabled", id: "fixture-no-eager", catalogId: "claude-sonnet-4-5", overrides: { compat: { supportsEagerToolInputStreaming: false } }, messages: base },
  { name: "strict_optional_nullable", id: "claude-sonnet-4-5", messages: [system({ toolsAdded: [tool("read", "read", { constrainedSampling: { type: "json_schema", strict: "prefer" } })] }), u("hello")] },
  { name: "strict_prefer_invalid_falls_back", id: "claude-sonnet-4-5", messages: [system({ toolsAdded: [tool("read", "read", { parameters: { type: "object", properties: { x: { type: "integer", minimum: 1 } } }, constrainedSampling: { type: "json_schema", strict: "prefer" } })] }), u("hello")] },
  { name: "strict_require_invalid_errors", id: "claude-sonnet-4-5", messages: [system({ toolsAdded: [tool("read", "read", { parameters: { type: "object", properties: { x: { type: "integer", minimum: 1 } } }, constrainedSampling: { type: "json_schema", strict: "require" } })] }), u("hello")] },
  { name: "configured_betas_replace_defaults", id: "claude-fable-5-1", reasoning: "high", headers: { "anthropic-beta": "custom-one, custom-two,custom-one" }, messages: base },
  { name: "oauth_claude_code_identity", id: "claude-sonnet-4-5", oauth: true, messages: base },
  { name: "refusal_error", id: "claude-sonnet-4-5", messages: base, reply: { stop_reason: "refusal", stop_details: { explanation: "Policy explanation" } } },
  { name: "sensitive_error", id: "claude-sonnet-4-5", messages: base, reply: { stop_reason: "sensitive" } },
  { name: "unknown_stop_error", id: "claude-sonnet-4-5", messages: base, reply: { stop_reason: "new-stop" } },
  { name: "signed_redacted_tool_reply", id: "claude-fable-5-1", reasoning: "xhigh", messages: base, replyContent: [{ type: "thinking", thinking: "reason", signature: "signed" }, { type: "redacted_thinking", data: "opaque" }, t("answer"), { type: "tool_use", id: "new-call", name: "read", input: { path: "a.py" } }], reply: { stop_reason: "tool_use" } },
  { name: "oauth_tool_reply_name", id: "claude-sonnet-4-5", oauth: true, messages: base, replyContent: [{ type: "tool_use", id: "new-call", name: "Read", input: { path: "a.py" } }], reply: { stop_reason: "tool_use" } },
  { name: "fallback_response_cost", id: "claude-fable-5", responseModel: "claude-opus-5", messages: base },
  { name: "large_context_tier_cost", id: "claude-sonnet-4-5", messages: base, usage: { input_tokens: 200001, output_tokens: 30, cache_read_input_tokens: 11, cache_creation_input_tokens: 13, cache_creation: { ephemeral_1h_input_tokens: 5 } } },
  { name: "length_stop", id: "claude-sonnet-4-5", messages: base, reply: { stop_reason: "max_tokens" } },
  { name: "pause_stop", id: "claude-sonnet-4-5", messages: base, reply: { stop_reason: "pause_turn" } },
  { name: "null_output_cap_uses_model_default", id: "claude-sonnet-4-5", maxTokens: null, messages: base },
  { name: "explicit_output_cap_with_thinking", id: "claude-sonnet-4-5", maxTokens: 2000, reasoning: "high", messages: base },
  { name: "strict_prefer_server_grammar_fallback", id: "claude-sonnet-4-5", strictRejection: "The compiled grammar is too large", messages: [system({ toolsAdded: [tool("read", "read", { constrainedSampling: { type: "json_schema", strict: "prefer" } })] }), u("hello")] },
  { name: "strict_prefer_tool_count_fallback_keeps_required", id: "claude-sonnet-4-5", strictRejection: "Too many strict tools (20)", messages: [system({ toolsAdded: [tool("read", "read", { constrainedSampling: { type: "json_schema", strict: "prefer" } }), tool("write", "write", { constrainedSampling: { type: "json_schema", strict: "require" } })] }), u("hello")] },
  { name: "strict_prefer_native_addition_union_fallback", id: "claude-fable-5-1", strictRejection: "Schemas contains too many parameters with union types (20)", messages: [system(), u("first"), a([t("prior")]), { role: "system", content: "", toolsAdded: [tool("write", "write", { constrainedSampling: { type: "json_schema", strict: "prefer" } })], timestamp: 4 }, u("next", 5)] },
];
const cases = [];
for (const input of inputs) {
  const model = { ...MODELS.anthropic[input.catalogId ?? input.id], id: input.id, baseUrl: "https://offline.invalid", ...input.overrides };
  const requests = [];
  const usage = input.usage ?? { input_tokens: 7, output_tokens: 3, cache_read_input_tokens: 11, cache_creation_input_tokens: 13, cache_creation: { ephemeral_1h_input_tokens: 5 }, output_tokens_details: { thinking_tokens: 2 } };
  const fetch = async (url, init) => {
    const headers = new Headers(init.headers);
    requests.push({ body: JSON.parse(init.body), headers: { ...(headers.has("anthropic-beta") ? { "anthropic-beta": headers.get("anthropic-beta") } : {}), ...(headers.has("authorization") ? { authorization: headers.get("authorization") } : {}), ...(headers.has("x-api-key") ? { "x-api-key": headers.get("x-api-key") } : {}), ...(headers.has("x-app") ? { "x-app": headers.get("x-app") } : {}), ...(headers.has("user-agent") && input.oauth ? { "user-agent": headers.get("user-agent") } : {}) } });
    if (input.strictRejection && requests.length === 1) {
      return new Response(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: input.strictRejection } }), { status: 400, headers: { "content-type": "application/json" } });
    }
    const events = [
      { type: "message_start", message: { id: "offline", type: "message", role: "assistant", content: [], model: input.responseModel ?? model.id, stop_reason: null, stop_sequence: null, usage } },
    ];
    for (const [index, block] of (input.replyContent ?? [t("offline answer")]).entries()) {
      const start = block.type === "text" ? { type: "text", text: "" } : block.type === "thinking" ? { type: "thinking", thinking: "", signature: "" } : block.type === "tool_use" ? { ...block, input: {} } : block;
      events.push({ type: "content_block_start", index, content_block: start });
      if (block.type === "text") events.push({ type: "content_block_delta", index, delta: { type: "text_delta", text: block.text } });
      if (block.type === "thinking") {
        events.push({ type: "content_block_delta", index, delta: { type: "thinking_delta", thinking: block.thinking } });
        events.push({ type: "content_block_delta", index, delta: { type: "signature_delta", signature: block.signature } });
      }
      if (block.type === "tool_use") events.push({ type: "content_block_delta", index, delta: { type: "input_json_delta", partial_json: JSON.stringify(block.input) } });
      events.push({ type: "content_block_stop", index });
    }
    events.push({ type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null, ...input.reply }, usage }, { type: "message_stop" });
    return new Response(events.map(event => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join(""), { status: 200, headers: { "content-type": "text/event-stream" } });
  };
  const reply = await streamSimple(model, { messages: structuredClone(input.messages) }, {
    apiKey: input.oauth ? "sk-ant-oat-fixture-only" : "fixture-only", fetch, maxRetries: 0,
    reasoning: input.reasoning, cacheRetention: input.cacheRetention, headers: input.headers,
    maxTokens: input.maxTokens,
  }).result();
  const { timestamp, durationMs, ...canonical } = reply;
  if (canonical.diagnostics) canonical.diagnostics = canonical.diagnostics.map(({ timestamp, ...diagnostic }) => ({ ...diagnostic, timestamp: 0 }));
  cases.push({ input: { ...input, model }, expected: { requests, reply: canonical } });
}
const files = ["packages/ai/src/api/anthropic-messages.ts", "packages/ai/src/api/transform-messages.ts", "packages/ai/src/api/constrained-sampling.ts", "packages/ai/src/api/simple-options.ts", "packages/ai/src/utils/transcript.ts", "packages/ai/src/utils/text.ts", "packages/ai/src/utils/diagnostics.ts", "packages/ai/src/models.ts"];
const source_sha256 = Object.fromEntries(files.map(name => [name, createHash("sha256").update(readFileSync(path.join(root, name))).digest("hex")]));
console.log(JSON.stringify({ baseline: `v1.4.0@${commit}`, method: "Original TypeScript streamSimple and Anthropic SDK with deterministic offline SSE; no network/account/paid request.", source_sha256, cases }, null, 2));
