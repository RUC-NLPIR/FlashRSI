/** Actual pinned Pi OpenAI providers with deterministic offline SSE replies. */
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
const source = name => import(pathToFileURL(path.join(root, name)).href);
const providers = { "openai-completions": await source("packages/ai/src/api/openai-completions.ts"), "openai-responses": await source("packages/ai/src/api/openai-responses.ts") };
const { MODELS } = await import(pathToFileURL(path.join(pkg, "dist/models.generated.js")).href);
const zero = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const t = text => ({ type: "text", text });
const tool = (name, description = name) => ({ name, description, parameters: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } });
const read = tool("read"), write = tool("write"), edit = tool("edit");
const grammar = { name: "code", description: "Execute grammar input", parameters: { type: "object", properties: { program: { type: "string" } }, required: ["program"] }, constrainedSampling: { type: "grammar", variants: { openai_lark: 'start: /[\\s\\S]*/' } } };
const sys = (extra = {}) => ({ role: "system", content: "base prompt", toolsAdded: [read], timestamp: 0, ...extra });
const user = (content = "next", timestamp = 1) => ({ role: "user", content, timestamp });
const assistant = (content, extra = {}) => ({ role: "assistant", api: "openai-responses", provider: "openai", model: "gpt-6-sol", stopReason: "stop", content, usage: zero, timestamp: 2, ...extra });
const canonicalCall = (id = "call_code|ctc_prior", extra = {}) => ({ type: "toolCall", id, name: "code", arguments: { program: "hello\n" }, ...extra });
const result = (id = "call_code|ctc_prior") => ({ role: "toolResult", toolCallId: id, toolName: "code", content: [t("executed")], isError: false, timestamp: 3 });
const inputs = [
  { name: "completion_native_additions", provider: "moonshotai", id: "kimi-k3", api: "openai-completions", context: [sys(), user("first"), { role: "system", content: "", toolsAdded: [write], timestamp: 2 }, user("next", 3)] },
  { name: "completion_removal_folds_old_tool_state", provider: "moonshotai", id: "kimi-k3", api: "openai-completions", context: [sys({ toolsAdded: [read, write] }), user("first"), { role: "system", content: "removed read", toolsRemoved: [{ name: "read" }], timestamp: 2 }, user("later", 3), { role: "system", content: "", toolsAdded: [edit], timestamp: 4 }, user("next", 5)] },
  { name: "completion_redefinition_folds_through_redefinition", provider: "moonshotai", id: "kimi-k3", api: "openai-completions", context: [sys(), user("first"), { role: "system", content: "redefine", toolsAdded: [tool("read", "new read")], timestamp: 2 }, user("later", 3), { role: "system", content: "", toolsAdded: [write], timestamp: 4 }, user("next", 5)] },
  { name: "responses_additional_tools_remove_and_readd", id: "gpt-6-sol", api: "openai-responses", reasoning: "high", context: [sys({ toolsAdded: [read, write] }), user("first"), assistant([t("prior")], { providerThinkingLevel: "low" }), { role: "system", content: "updated", sections: { goal: "new" }, toolsRemoved: [{ name: "read" }], toolsAdded: [edit], timestamp: 3 }, user("later", 4), { role: "system", content: "", toolsAdded: [read], timestamp: 5 }, user("next", 6)] },
  { name: "responses_additional_tools_redefinition", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user("first"), { role: "system", content: "", toolsRemoved: [{ name: "read" }], toolsAdded: [tool("read", "new read")], timestamp: 2 }, user("next", 3)] },
  { name: "responses_tool_search_additions", id: "gpt-6-sol", api: "openai-responses", compat: { supportsAdditionalTools: false, supportsToolSearch: true }, context: [sys(), user("first"), { role: "system", content: "", toolsAdded: [write], timestamp: 2 }, user("next", 3)] },
  { name: "responses_tool_search_removal_fold", id: "gpt-6-sol", api: "openai-responses", compat: { supportsAdditionalTools: false, supportsToolSearch: true }, context: [sys({ toolsAdded: [read, write] }), user("first"), { role: "system", content: "removed read", toolsRemoved: [{ name: "read" }], timestamp: 2 }, user("later", 3), { role: "system", content: "", toolsAdded: [edit], timestamp: 4 }, user("next", 5)] },
  { name: "completion_grammar_history_and_custom_reply", id: "gpt-6-sol", api: "openai-completions", context: [sys({ toolsAdded: [grammar] }), user("code"), assistant([canonicalCall("call_code")], { api: "openai-completions", stopReason: "toolUse" }), result("call_code"), user("again")], customReply: true },
  { name: "responses_grammar_history_and_custom_reply", id: "gpt-6-sol", api: "openai-responses", context: [sys({ toolsAdded: [grammar] }), user("code"), assistant([canonicalCall(undefined, { namespace: "fixture" })], { stopReason: "toolUse" }), result(), user("again")], customReply: true },
  { name: "responses_foreign_grammar_id_replay", id: "gpt-6-sol", api: "openai-responses", context: [sys({ toolsAdded: [grammar] }), user("code"), assistant([canonicalCall("call|foreign @id")], { api: "openai-completions", provider: "other", model: "other", stopReason: "toolUse" }), result("call|foreign @id"), user("again")], customReply: true },
  { name: "completion_unknown_custom_reply_uses_input", id: "gpt-6-sol", api: "openai-completions", context: [sys({ toolsAdded: [grammar] }), user("code")], customReply: true, replyName: "unknown" },
  { name: "responses_unknown_custom_reply_uses_input", id: "gpt-6-sol", api: "openai-responses", context: [sys({ toolsAdded: [grammar] }), user("code")], customReply: true, replyName: "unknown" },
  ...["openai-completions", "openai-responses"].map(api => ({ name: `invalid_grammar_history_${api}`, id: "gpt-6-sol", api, context: [sys({ toolsAdded: [grammar] }), user("code"), assistant([canonicalCall("invalid", { arguments: { program: 42 } })], { api, stopReason: "toolUse" }), result("invalid"), user("again")] })),
  ...["length", "content_filter", "network_error", "fixture_unknown", null].map(finishReason => ({ name: `completion_finish_${finishReason}`, id: "gpt-6-sol", api: "openai-completions", context: [sys(), user()], finishReason })),
  { name: "responses_refusal_and_text", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], output: [{ type: "message", id: "msg_reply", role: "assistant", status: "completed", phase: "final_answer", content: [{ type: "refusal", refusal: "Policy refusal. " }, { type: "output_text", text: "Safe alternative.", annotations: [] }] }] },
  ...["max_output_tokens", "content_filter", null].map(incompleteReason => ({ name: `responses_incomplete_${incompleteReason}`, id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "incomplete", ...(incompleteReason ? { incompleteReason } : {}) })),
  { name: "responses_reasoning_summaries_and_signature", id: "gpt-6-sol", api: "openai-responses", reasoning: "high", context: [sys(), user()], output: [{ type: "reasoning", id: "rs_reply", summary: [{ type: "summary_text", text: "First thought" }, { type: "summary_text", text: "Second thought" }], encrypted_content: "opaque-private-signature" }, { type: "message", id: "msg_reply", role: "assistant", status: "completed", content: [{ type: "output_text", text: "final answer", annotations: [] }] }] },
  { name: "responses_reasoning_content_fallback", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], output: [{ type: "reasoning", id: "rs_content", summary: [], content: [{ type: "reasoning_text", text: "Reasoning content one" }, { type: "reasoning_text", text: "Reasoning content two" }] }] },
  { name: "responses_function_call_arguments", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], output: [{ type: "function_call", id: "fc_reply", call_id: "call_reply", name: "read", arguments: '{"path":"note.txt"}', namespace: "fixture" }] },
  { name: "responses_failed_error", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "failed", error: { code: "server_error", message: "Offline provider failed" } },
  { name: "responses_failed_incomplete_details", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "failed", incompleteReason: "fixture failure" },
  { name: "responses_failed_no_details", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "failed" },
  { name: "responses_cancelled", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "cancelled" },
  { name: "responses_unknown_status", id: "gpt-6-sol", api: "openai-responses", context: [sys(), user()], status: "fixture_unknown" },
];
const cases = [];
for (const input of inputs) {
  const provider = input.provider ?? "openai";
  const catalog = MODELS[provider]?.[input.id];
  if (!catalog) throw new Error(`Missing release model ${provider}/${input.id}`);
  const model = { ...structuredClone(catalog), api: input.api, baseUrl: "https://offline.invalid/v1", compat: { ...catalog.compat, ...input.compat } };
  const requests = [];
  const customInput = "hello\n😊\\\"";
  const name = input.replyName ?? "code";
  let response;
  if (input.api === "openai-completions") {
    response = { id: "chatcmpl_offline", object: "chat.completion", model: input.id, choices: [{ index: 0, message: { role: "assistant", content: input.customReply ? null : "offline answer", ...(input.customReply ? { tool_calls: [{ id: "call_reply", type: "custom", custom: { name, input: customInput } }] } : {}) }, finish_reason: input.customReply ? "tool_calls" : "stop" }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12, prompt_tokens_details: { cached_tokens: 3, cache_write_tokens: 1 }, completion_tokens_details: { reasoning_tokens: 1 } } };
  } else {
    response = { id: "resp_offline", object: "response", model: input.id, status: "completed", output: [input.customReply ? { type: "custom_tool_call", id: "ctc_reply", call_id: "call_reply", name, input: customInput, namespace: "fixture" } : { type: "message", id: "msg_reply", role: "assistant", status: "completed", content: [{ type: "output_text", text: "offline answer", annotations: [] }] }], usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12, input_tokens_details: { cached_tokens: 3, cache_write_tokens: 1 }, output_tokens_details: { reasoning_tokens: 1 } } };
  }
  if (Object.hasOwn(input, "finishReason")) response.choices[0].finish_reason = input.finishReason;
  if (input.status) response.status = input.status;
  if (input.incompleteReason) response.incomplete_details = { reason: input.incompleteReason };
  if (input.error) response.error = input.error;
  if (input.output) response.output = input.output;
  const fetch = async (url, init) => {
    requests.push({ body: JSON.parse(init.body) });
    let events;
    if (input.api === "openai-completions") {
      const choice = response.choices[0];
      const delta = input.customReply ? { role: "assistant", tool_calls: [{ ...choice.message.tool_calls[0], index: 0 }] } : { role: "assistant", content: "offline answer" };
      events = [{ id: response.id, object: "chat.completion.chunk", model: input.id, choices: [{ index: 0, delta, finish_reason: null }] }, { id: response.id, object: "chat.completion.chunk", model: input.id, choices: [{ index: 0, delta: {}, finish_reason: choice.finish_reason }], usage: response.usage }];
      return new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join("") + "data: [DONE]\n\n", { status: 200, headers: { "content-type": "text/event-stream" } });
    }
    events = [{ type: "response.created", response: { id: response.id } }];
    for (const [output_index, item] of response.output.entries()) {
      const initial = { ...item, ...(item.type === "custom_tool_call" ? { input: "" } : item.type === "function_call" ? { arguments: "" } : item.type === "reasoning" ? { summary: [], content: [] } : { content: [] }) };
      events.push({ type: "response.output_item.added", output_index, item: initial });
      if (item.type === "custom_tool_call") events.push({ type: "response.custom_tool_call_input.delta", output_index, item_id: item.id, delta: item.input }, { type: "response.custom_tool_call_input.done", output_index, item_id: item.id, input: item.input });
      else if (item.type === "function_call") events.push({ type: "response.function_call_arguments.delta", output_index, item_id: item.id, delta: item.arguments }, { type: "response.function_call_arguments.done", output_index, item_id: item.id, arguments: item.arguments });
      else if (item.type === "reasoning") {
        for (const [summary_index, part] of (item.summary ?? []).entries()) events.push({ type: "response.reasoning_summary_text.delta", output_index, summary_index, item_id: item.id, delta: part.text }, { type: "response.reasoning_summary_part.done", output_index, summary_index, item_id: item.id, part });
        for (const [content_index, part] of (item.content ?? []).entries()) events.push({ type: "response.reasoning_text.delta", output_index, content_index, item_id: item.id, delta: part.text });
      } else if (item.type === "message") {
        for (const [content_index, part] of item.content.entries()) events.push({ type: part.type === "refusal" ? "response.refusal.delta" : "response.output_text.delta", output_index, content_index, item_id: item.id, delta: part.text ?? part.refusal });
      }
      events.push({ type: "response.output_item.done", output_index, item });
    }
    events.push({ type: input.status === "failed" ? "response.failed" : input.status === "incomplete" ? "response.incomplete" : "response.completed", response });
    return new Response(events.map(event => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join(""), { status: 200, headers: { "content-type": "text/event-stream" } });
  };
  const reply = await providers[input.api].streamSimple(model, { messages: structuredClone(input.context) }, { apiKey: "sk-offline-fixture", fetch, maxRetries: 0, reasoning: input.reasoning }).result();
  const { timestamp, durationMs, ...canonical } = reply;
  const config = { llm: { model_name: `${provider}/${input.id}`, model_api: input.api, base_url: model.baseUrl, api_key: "sk-offline-fixture", max_retries: 0 } };
  cases.push({ input: { ...input, config, model, response }, expected: { requests, reply: canonical } });
}
const files = ["packages/ai/src/utils/transcript.ts", "packages/ai/src/api/constrained-sampling.ts", "packages/ai/src/api/openai-completions.ts", "packages/ai/src/api/openai-responses.ts", "packages/ai/src/api/openai-responses-shared.ts", "packages/ai/src/models.ts"];
const source_sha256 = Object.fromEntries(files.map(name => [name, createHash("sha256").update(readFileSync(path.join(root, name))).digest("hex")]));
console.log(JSON.stringify({ baseline: `v1.4.0@${commit}`, method: "Actual original Completion and Responses streamSimple -> pinned SDK -> deterministic offline SSE. Full request bodies and final canonical replies. No network/account/paid model.", source_sha256, cases }, null, 2));
