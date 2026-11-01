/** Original pinned Anthropic streaming provider; every push captured synchronously. */
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
if (JSON.parse(readFileSync(path.join(pkg, "package.json"))).version !== "1.4.0") throw new Error("Wrong model release");
const { MODELS } = await import(pathToFileURL(path.join(pkg, "dist/models.generated.js")).href);
const source = name => import(pathToFileURL(path.join(root, name)).href);
const { streamSimple } = await source("packages/ai/src/api/anthropic-messages.ts");
const json = await source("packages/ai/src/utils/json-parse.ts");
const tool = { name: "read", description: "Read a file", parameters: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } };
const context = [{ role: "system", content: "offline stream fixture", toolsAdded: [tool], timestamp: 0 }, { role: "user", content: "continue", timestamp: 1 }];
const usage = { input_tokens: 7, output_tokens: 1, cache_read_input_tokens: 11, cache_creation_input_tokens: 13, cache_creation: { ephemeral_1h_input_tokens: 5 }, output_tokens_details: { thinking_tokens: 999 } };
const begin = (extra = {}) => ({ type: "message_start", message: { id: "msg_stream", type: "message", role: "assistant", model: "claude-sonnet-4-5", content: [], stop_reason: null, usage, ...extra } });
const start = (index, content_block) => ({ type: "content_block_start", index, content_block });
const delta = (index, delta) => ({ type: "content_block_delta", index, delta });
const stop = index => ({ type: "content_block_stop", index });
const end = (reason = "end_turn", extra = {}) => ({ type: "message_delta", delta: { stop_reason: reason }, usage: { output_tokens: 9, output_tokens_details: { thinking_tokens: 2 } }, ...extra });
const done = { type: "message_stop" };
const text = [start(0, { type: "text", text: "" }), delta(0, { type: "text_delta", text: "Hello " }), delta(0, { type: "text_delta", text: "世界😊" }), stop(0)];
const toolEvents = (chunks, initial = {}, index = 2, name = "read") => [start(index, { type: "tool_use", id: `call_${index}`, name, input: initial }), ...chunks.map(partial_json => delta(index, { type: "input_json_delta", partial_json })), stop(index)];
const inputs = [
  { name: "text_multiple_deltas", rawEvents: [begin(), ...text, end(), done] },
  { name: "text_initial_seed_empty_delta", rawEvents: [begin(), start(4, { type: "text", text: "seed" }), delta(4, { type: "text_delta", text: "" }), delta(4, { type: "text_delta", text: " tail" }), stop(4), end(), done] },
  { name: "signed_and_redacted_thinking", id: "claude-fable-5-1", reasoning: "high", rawEvents: [begin({ model: "claude-fable-5-1" }), start(3, { type: "thinking", thinking: "seed ", signature: "initial-" }), delta(3, { type: "thinking_delta", thinking: "thought" }), delta(3, { type: "signature_delta", signature: "signature-" }), delta(3, { type: "signature_delta", signature: "tail" }), stop(3), start(7, { type: "redacted_thinking", data: "opaque-encrypted" }), stop(7), ...text, end(), done] },
  { name: "tool_nested_partial_json", rawEvents: [begin(), ...toolEvents(['{"path":"no', 'te.txt","nested":{"list":[1,', 'true,null,{"k":"v', '"}]},"n":2e', '3}']), end("tool_use"), done] },
  { name: "tool_empty_input_overwrites_seed", rawEvents: [begin(), ...toolEvents([], { path: "seed.txt" }), end("tool_use"), done] },
  { name: "tool_control_and_escape_repair", rawEvents: [begin(), ...toolEvents(['{"path":"C:\\work\\new', 'line\nraw"}']), end("tool_use"), done] },
  { name: "tool_incomplete_final_arguments", rawEvents: [begin(), ...toolEvents(['{"path":']), end("tool_use"), done] },
  { name: "tool_trailing_comma_arguments", rawEvents: [begin(), ...toolEvents(['{"path":"x",}']), end("tool_use"), done] },
  { name: "tool_array_arguments_error", rawEvents: [begin(), ...toolEvents(['[1,2]']), end("tool_use"), done] },
  { name: "tool_partial_unicode_escape", rawEvents: [begin(), ...toolEvents(['{"path":"\\u', '4e', '2d"}']), end("tool_use"), done] },
  { name: "interleaved_provider_indices", rawEvents: [begin(), start(9, { type: "text", text: "a" }), start(2, { type: "tool_use", id: "call_parallel", name: "read", input: {} }), delta(2, { type: "input_json_delta", partial_json: '{"path":"x"}' }), delta(9, { type: "text_delta", text: "b" }), stop(9), stop(2), end("tool_use"), done] },
  { name: "oauth_tool_canonical_name", oauth: true, rawEvents: [begin(), ...toolEvents(['{"path":"x"}'], {}, 0, "Read"), end("tool_use"), done] },
  { name: "usage_partial_deltas_keep_initial", rawEvents: [begin(), ...text, end(null, { usage: { output_tokens: 3, input_tokens: null, cache_read_input_tokens: null } }), end("end_turn", { usage: { output_tokens: 4, cache_creation: { ephemeral_1h_input_tokens: 2 }, output_tokens_details: { thinking_tokens: 1 } } }), done] },
  { name: "fallback_response_cost", id: "claude-fable-5", rawEvents: [begin({ model: "claude-opus-5" }), start(99, { type: "fallback", model: "claude-opus-5" }), ...text, end(), done] },
  { name: "large_context_cost_tier", rawEvents: [begin({ usage: { ...usage, input_tokens: 200001 } }), ...text, end(), done] },
  { name: "input_transformation_diagnostic", rawEvents: [begin({ input_transformations: [{ type: "old", path: "old" }] }), ...text, end("end_turn", { input_transformations: [{ type: "repair", path: ["messages", 1], reason: "invalid-signature", extra: "ignored" }, { type: null, path: null, reason: "stripped" }, {}] }), done] },
  { name: "input_transformations_cleared", rawEvents: [begin({ input_transformations: [{ type: "old" }] }), ...text, end("end_turn", { input_transformations: [] }), done] },
  ...["max_tokens", "pause_turn", "stop_sequence", "sensitive", "unknown-stop"].map(reason => ({ name: `stop_${reason}`, rawEvents: [begin(), ...text, end(reason), done] })),
  { name: "refusal_explanation", rawEvents: [begin(), ...text, end("refusal", { delta: { stop_reason: "refusal", stop_details: { explanation: "Policy explanation" } } }), done] },
  { name: "refusal_default", rawEvents: [begin(), ...text, end("refusal"), done] },
  { name: "stream_without_stop_reason", rawEvents: [begin(), ...text, done] },
  { name: "stream_without_message_stop", rawEvents: [begin(), ...text, end()] },
  { name: "empty_stream", rawEvents: [] },
  { name: "unknown_block_and_ping_ignored", rawEvents: [{ type: "ping" }, begin(), start(42, { type: "server_tool_use", name: "server_tool" }), delta(42, { type: "text_delta", text: "ignored" }), stop(42), ...text, end(), done] },
  { name: "unsupported_mid_output_fallback", rawEvents: [begin(), ...text, start(3, { type: "fallback", model: "other-model" }), end(), done] },
  { name: "provider_error_retains_partial", rawEvents: [begin(), start(4, { type: "text", text: "partial" }), { type: "error", error: { type: "overloaded_error", message: "offline failure" } }] },
  { name: "abort_partial_text", abortAfter: 2, rawEvents: [begin(), start(4, { type: "text", text: "" }), delta(4, { type: "text_delta", text: "partial" }), stop(4), end(), done] },
  { name: "abort_partial_tool", abortAfter: 2, rawEvents: [begin(), start(6, { type: "tool_use", id: "partial_call", name: "read", input: {} }), delta(6, { type: "input_json_delta", partial_json: '{"path":"partial' }), stop(6), end("tool_use"), done] },
  { name: "strict_fallback_diagnostic_before_start", strictRejection: "The compiled grammar is too large", context: [{ role: "system", content: "offline", toolsAdded: [{ ...tool, constrainedSampling: { type: "json_schema", strict: "prefer" } }], timestamp: 0 }, context[1]], rawEvents: [begin(), ...text, end(), done] },
];
function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "durationMs").map(([key, item]) => [key, key === "timestamp" ? 0 : normalize(item)]));
  return value;
}
const cases = [];
for (const input of inputs) {
  const id = input.id ?? "claude-sonnet-4-5";
  const model = { ...structuredClone(MODELS.anthropic[id]), baseUrl: "https://offline.invalid" };
  const messages = input.context ?? context;
  const config = { llm: { model_name: `anthropic/${id}`, base_url: model.baseUrl, model_api: "anthropic-messages", api_key: input.oauth ? "sk-ant-oat-offline-only" : "fixture-only", max_retries: 0 } };
  const events = [];
  const controller = new AbortController();
  let fetchCalls = 0;
  const observedRaw = [];
  const fetch = async () => {
    fetchCalls++;
    if (input.strictRejection && fetchCalls === 1) return new Response(JSON.stringify({ type: "error", error: { type: "invalid_request_error", message: input.strictRejection } }), { status: 400, headers: { "content-type": "application/json" } });
    let position = 0;
    const body = new ReadableStream({ pull(target) {
      if (position >= input.rawEvents.length) return target.close();
      const event = input.rawEvents[position++];
      target.enqueue(new TextEncoder().encode(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`));
    } });
    return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  };
  const stream = streamSimple(model, { messages: structuredClone(messages) }, { apiKey: config.llm.api_key, fetch, maxRetries: 0, reasoning: input.reasoning, signal: controller.signal, onProviderStreamEvent(event) {
    observedRaw.push(structuredClone(event));
    if (observedRaw.length - 1 === input.abortAfter) controller.abort();
  } });
  const originalPush = stream.push.bind(stream);
  stream.push = event => { originalPush(event); events.push(normalize(structuredClone(event))); };
  const reply = normalize(await stream.result());
  delete reply.timestamp;
  cases.push({ input: { ...input, id, context: messages, model, config }, expected: { fetchCalls, observedRaw, events, reply } });
}
const jsonInputs = ["", " ", "{", '{"path":', '{"path":"a', '{"path":"a\\', '{"path":"\\u', '{"path":"\\u4e', '{"path":"\\u4e2d"}', '{"a":[1,', '{"a":[1,tru', '{"a":{"b":n', '{"a":2e', '{"a":-Inf', '{"a":f', '{"a":false,}', '{"a":"C:\\work"}', '{"a":"x\ny"}', '[1,2]', 'null', 'true', '0', '"hello"', '{bad}', '{"path":"x",}', '{"a":1} trailing', '{"a" 1}', '{"a": [1 2]}', '{"a": "unterminated', '{"😊":}'];
const jsonCases = jsonInputs.map(input => ({ input, repaired: json.repairJson(input), partial: json.parseStreamingJson(input), final: json.parseToolCallArguments(input) }));
const files = ["packages/ai/src/api/anthropic-messages.ts", "packages/ai/src/utils/json-parse.ts", "packages/ai/src/utils/event-stream.ts", "packages/ai/src/utils/diagnostics.ts"];
const source_sha256 = Object.fromEntries(files.map(name => [name, createHash("sha256").update(readFileSync(path.join(root, name))).digest("hex")]));
console.log(JSON.stringify({ baseline: `v1.4.0@${commit}`, method: "Original streamSimple -> original SDK -> deterministic offline incremental SSE; synchronous snapshots of every original stream.push. Normalize only timestamp and duration timing. No network/account/paid model.", source_sha256, partial_json: { version: "0.1.7", sha256: createHash("sha256").update(readFileSync(path.join(deps, "partial-json/dist/index.js"))).digest("hex") }, cases, jsonCases }, null, 2));
