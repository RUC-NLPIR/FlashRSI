/** Offline summary-provider oracle, executing original pinned Pi TypeScript.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 *   ./tests/fixtures/generate_pi_summary_options_upstream.mjs > ./tests/fixtures/pi_summary_options_upstream.json
 * Requires Node 24 for TypeScript stripping. Custom fetch returns fixed SSE;
 * no real endpoint, account credentials, or paid model is used.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = process.env.PI_REFERENCE_SOURCE;
const deps = process.env.PI_REFERENCE_DEPS;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim() !== commit) {
  throw new Error("Wrong Pi source revision");
}
const packageRoot = path.join(deps, "@earendil-works/pi-ai");
const releasePackage = JSON.parse(readFileSync(path.join(packageRoot, "package.json")));
if (releasePackage.version !== "1.4.0") throw new Error("Wrong hydrated model catalog version");
const source = name => import(pathToFileURL(path.join(root, name)).href);
const anthropic = await source("packages/ai/src/api/anthropic-messages.ts");
const simple = await source("packages/ai/src/api/simple-options.ts");
const estimate = await source("packages/ai/src/utils/estimate.ts");
const transcript = await source("packages/ai/src/utils/transcript.ts");
const { completeSummarization } = await source("packages/coding-agent/src/core/compaction/compaction.ts");
const { MODELS } = await import(pathToFileURL(path.join(packageRoot, "dist/models.generated.js")).href);
const zero = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const text = value => ({ type: "text", text: value });
const user = value => ({ role: "user", content: value, timestamp: 1 });
const summaryContext = { messages: [
  { role: "system", content: "You are a context summarization assistant. Only output a summary.", timestamp: 0 },
  user([text("<conversation>\n[User]: update files\n[Assistant]: completed\n</conversation>\n\nSummarize the progress.")]),
] };

function responseSse(modelId) {
  const events = [
    { type: "message_start", message: { id: "msg_offline", type: "message", role: "assistant", content: [], model: modelId,
      stop_reason: null, stop_sequence: null, usage: { input_tokens: 1, output_tokens: 0 } } },
    { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
    { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "offline summary" } },
    { type: "content_block_stop", index: 0 },
    { type: "message_delta", delta: { stop_reason: "end_turn", stop_sequence: null }, usage: { output_tokens: 1 } },
    { type: "message_stop" },
  ];
  return new Response(events.map(event => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join(""), {
    status: 200, headers: { "content-type": "text/event-stream", "request-id": "offline-fixture" },
  });
}

const providerInputs = [
  { name: "legacy_off", id: "claude-sonnet-4-5", thinkingLevel: "off" },
  { name: "legacy_high", id: "claude-sonnet-4-5", thinkingLevel: "high" },
  ...["high", "xhigh", "max", "off"].map(thinkingLevel => ({ name: `adaptive_${thinkingLevel}`, id: "claude-opus-4-7", thinkingLevel })),
  ...["high", "off"].map(thinkingLevel => ({ name: `managed_fable_${thinkingLevel}`, id: "claude-fable-5-1", thinkingLevel })),
  ...["high", "off"].map(thinkingLevel => ({ name: `managed_haiku_${thinkingLevel}`, id: "claude-haiku-5-5", thinkingLevel })),
  ...["high", "off"].map(thinkingLevel => ({ name: `fallback_fable_${thinkingLevel}`, id: "claude-fable-5", thinkingLevel })),
  ...["high", "off"].map(thinkingLevel => ({
    name: `synthetic_nonreasoning_${thinkingLevel}`,
    catalogId: "claude-sonnet-4-5",
    id: "fixture-claude-nonreasoning",
    thinkingLevel,
    overrides: { reasoning: false },
  })),
  { name: "legacy_small_context_high", id: "claude-sonnet-4-5", thinkingLevel: "high", overrides: { contextWindow: 5000 } },
  { name: "legacy_small_context_off", id: "claude-sonnet-4-5", thinkingLevel: "off", overrides: { contextWindow: 5000 } },
];
const providers = [];
for (const input of providerInputs) {
  const catalogId = input.catalogId ?? input.id;
  const catalog = MODELS.anthropic[catalogId];
  if (!catalog) throw new Error(`Missing source catalog model ${catalogId}`);
  // Synthetic models still execute the original provider using complete source
  // metadata. Keep catalog provenance explicit instead of pretending these ids
  // exist in the release catalog.
  const model = { ...catalog, id: input.id, baseUrl: "https://offline.invalid", cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, ...input.overrides };
  const requests = [];
  const optionsSeen = [];
  const fetch = async (url, init) => {
    const headers = new Headers(init.headers);
    requests.push({ url: String(url), body: JSON.parse(init.body), headers: {
      ...(headers.has("anthropic-beta") ? { "anthropic-beta": headers.get("anthropic-beta") } : {}),
      "anthropic-version": headers.get("anthropic-version"),
      "content-type": headers.get("content-type"),
    } });
    return responseSse(model.id);
  };
  const context = transcript.normalizeContext(structuredClone(summaryContext));
  // Same selection rule as createSummarizationOptions(): off is omitted.
  const reasoning = model.reasoning && input.thinkingLevel && input.thinkingLevel !== "off" ? input.thinkingLevel : undefined;
  const options = { apiKey: "fixture-only", ...(reasoning ? { reasoning } : {}) };
  const streamFn = (requestedModel, requestedContext, requestedOptions) => {
    optionsSeen.push({ ...("reasoning" in requestedOptions ? { reasoning: requestedOptions.reasoning } : {}),
      cacheRetention: requestedOptions.cacheRetention, hasSessionId: !!requestedOptions.sessionId });
    return anthropic.streamSimple(requestedModel, requestedContext, { ...requestedOptions, fetch, maxRetries: 0 });
  };
  const reply = await completeSummarization(model, context, options, streamFn);
  if (reply.stopReason !== "stop") throw new Error(`Offline provider failed: ${reply.errorMessage}`);
  const metadata = Object.fromEntries(["id", "api", "provider", "baseUrl", "reasoning", "contextWindow", "maxTokens", "compat", "thinkingLevelMap"]
    .filter(key => model[key] !== undefined).map(key => [key, model[key]]));
  providers.push({ input: { ...input, model: metadata, context: summaryContext }, expected: { requests, options: optionsSeen,
    stopReason: reply.stopReason, ...(reply.providerThinkingLevel ? { providerThinkingLevel: reply.providerThinkingLevel } : {}) } });
}

const tokenInputs = [
  { name: "empty", model: { contextWindow: 128000, maxTokens: 128000 }, context: { messages: [] }, output: 128000 },
  { name: "small", model: { contextWindow: 5000, maxTokens: 2000 }, context: summaryContext, output: 2000 },
  { name: "huge", model: { contextWindow: 8192, maxTokens: 4096 }, context: { messages: [user("x".repeat(20000))] }, output: 4096 },
  { name: "zero_context", model: { contextWindow: 0, maxTokens: 300 }, context: { messages: [user("x".repeat(100))] }, output: 300 },
  { name: "zero_output", model: { contextWindow: 10000, maxTokens: 0 }, context: { messages: [] }, output: 0 },
  { name: "unicode_system_sections_tools", model: { contextWindow: 5000, maxTokens: 5000 }, context: { messages: [
    { role: "system", content: "根提示😊", sections: { goal: "项目目标", context: "详细上下文😊😊", removed: null },
      toolsAdded: [{ name: "read", description: "读取", parameters: { type: "object", properties: { path: { type: "string" } } } }],
      toolsRemoved: [{ name: "edit" }], timestamp: 0 },
    user([text("😊".repeat(7)), text("Unicode 参数与文件")]),
  ] }, output: 5000 },
  { name: "usage_backed", model: { contextWindow: 10000, maxTokens: 8000 }, context: { messages: [
    user("initial"), { role: "assistant", content: [text("done")], usage: { ...zero, input: 100, output: 5, totalTokens: 105 }, stopReason: "stop", timestamp: 2 },
    { role: "user", content: "trailing input", timestamp: 3 },
  ] }, output: 8000 },
  { name: "stale_usage_after_new_prefix", model: { contextWindow: 10000, maxTokens: 8000 }, context: { messages: [
    { role: "system", content: "a newer compacted prefix", timestamp: 100 },
    { role: "assistant", content: [text("old retained")], usage: { ...zero, input: 9000, totalTokens: 9000 }, stopReason: "stop", timestamp: 2 },
    { role: "user", content: "new request", timestamp: 101 },
  ] }, output: 8000 },
];
const tokens = tokenInputs.map(input => ({ input, expected: {
  estimate: estimate.estimateContextTokens(input.context),
  messageTokens: input.context.messages.map(message => estimate.estimateMessageTokens(message)),
  clamped: simple.clampMaxTokensToContext(input.model, input.context, input.output),
} }));
const sources = ["packages/ai/src/api/anthropic-messages.ts", "packages/ai/src/api/simple-options.ts", "packages/ai/src/utils/estimate.ts",
  "packages/ai/src/utils/text.ts", "packages/ai/src/utils/transcript.ts", "packages/coding-agent/src/core/compaction/compaction.ts"];
const source_sha256 = Object.fromEntries(sources.map(name => [name, createHash("sha256").update(readFileSync(path.join(root, name))).digest("hex")]));
console.log(JSON.stringify({ baseline: `v1.4.0@${commit}`, method: "Actual original TypeScript completeSummarization -> anthropic.streamSimple -> SDK custom fetch; original estimateContextTokens/estimateMessageTokens/clampMaxTokensToContext. Fixed offline SSE, no network or paid model requests. Hydrated model metadata only comes from matching pi-ai 1.4.0 release.",
  source_sha256, release: { "@earendil-works/pi-ai": releasePackage.version }, providers, tokens }, null, 2));
