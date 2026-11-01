/** Source-only Pi tool/schema oracle; provider onPayload aborts before fetch. */
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
const transcript = await source("packages/ai/src/utils/transcript.ts");
const constrained = await source("packages/ai/src/api/constrained-sampling.ts");
const responses = await source("packages/ai/src/api/openai-responses-shared.ts");
const completions = await source("packages/ai/src/api/openai-completions.ts");
const { MODELS } = await import(pathToFileURL(path.join(pkg, "dist/models.generated.js")).href);
const tool = (name, extra = {}) => ({ name, description: `${name} fixture`, parameters: { type: "object", properties: { path: { type: "string" }, optional: { type: "number" } }, required: ["path"] }, ...extra });
const a = tool("read"), b = tool("write"), c = tool("edit");
const system = extra => ({ role: "system", content: "", timestamp: 0, ...extra });
const user = { role: "user", content: "hello", timestamp: 1 };
const contexts = [
  { name: "empty", messages: [] },
  { name: "initial", messages: [system({ toolsAdded: [a, b] }), user] },
  { name: "pure_additions", messages: [system({ toolsAdded: [a] }), user, system({ toolsAdded: [b] }), user, system({ toolsAdded: [c] })] },
  { name: "remove_then_add", messages: [system({ toolsAdded: [a, b] }), user, system({ toolsRemoved: [{ name: "read" }] }), user, system({ toolsAdded: [c] })] },
  { name: "same_name_redefinition", messages: [system({ toolsAdded: [a, b] }), user, system({ toolsAdded: [tool("read", { description: "new read" })] }), user, system({ toolsAdded: [c] })] },
  { name: "remove_readd_then_add", messages: [system({ toolsAdded: [a] }), system({ toolsRemoved: [{ name: "read" }] }), system({ toolsAdded: [a] }), user, system({ toolsAdded: [b] })] },
  { name: "no_leading_system", messages: [user, system({ toolsAdded: [a] }), user, system({ toolsAdded: [b] })] },
  { name: "remove_absent_name", messages: [system({ toolsAdded: [a] }), user, system({ toolsRemoved: [{ name: "absent" }] }), user, system({ toolsAdded: [b] })] },
  { name: "unchanged_name_is_still_redeclaration", messages: [system({ toolsAdded: [a] }), user, system({ toolsAdded: [a] }), user, system({ toolsAdded: [b] })] },
];
const resolutions = contexts.flatMap(context => ["none", "additions", "changes"].map(support => ({ input: { ...context, support }, expected: transcript.resolveTranscriptTools(context.messages, support) })));
const declarations = contexts.map(context => ({ input: context, expected: { current: transcript.getCurrentTools(context.messages), declared: transcript.getDeclaredTools(context.messages) } }));
const supports = [];
for (const supportsMidConvoSystemMessages of [false, true]) for (const supportsAdditionalTools of [false, true]) for (const supportsToolSearch of [false, true]) {
  const compat = { supportsMidConvoSystemMessages, supportsAdditionalTools, supportsToolSearch };
  supports.push({ input: { compat, api: "openai-responses" }, expected: responses.getResponsesToolSupport(compat) });
}
for (const supportsMidConvoSystemMessages of [false, true]) for (const supportsMidConvoToolAdditions of [false, true]) {
  const compat = { supportsMidConvoSystemMessages, supportsMidConvoToolAdditions };
  supports.push({ input: { compat, api: "openai-completions" }, expected: supportsMidConvoSystemMessages && supportsMidConvoToolAdditions ? "additions" : "none" });
}
const grammar = (extra = {}) => tool("code", { parameters: { type: "object", properties: { input: { type: "string" } }, required: ["input"] }, constrainedSampling: { type: "grammar", variants: { openai_lark: 'start: "hello"', openai_regex: "hello" } }, ...extra });
const grammarInputs = [
  { name: "no_constraint", tool: a, supports: true },
  { name: "lark_wins", tool: grammar(), supports: true },
  { name: "regex_fallback", tool: grammar({ constrainedSampling: { type: "grammar", variants: { openai_lark: " \n ", openai_regex: "  hello.*  " } } }), supports: true },
  { name: "unsupported_falls_back", tool: grammar(), supports: false },
  { name: "missing_variant_errors", tool: grammar({ constrainedSampling: { type: "grammar", variants: {} } }), supports: true },
  { name: "missing_variant_unsupported_ok", tool: grammar({ constrainedSampling: { type: "grammar", variants: {} } }), supports: false },
  { name: "non_object_schema", tool: grammar({ parameters: { type: "string" } }), supports: true },
  { name: "no_required", tool: grammar({ parameters: { type: "object", properties: { input: { type: "string" } } } }), supports: true },
  { name: "multiple_required", tool: grammar({ parameters: { type: "object", required: ["a", "b"], properties: { a: { type: "string" }, b: { type: "string" } } } }), supports: true },
  { name: "missing_property", tool: grammar({ parameters: { type: "object", required: ["input"], properties: {} } }), supports: true },
  { name: "non_string_property", tool: grammar({ parameters: { type: "object", required: ["input"], properties: { input: { type: "integer" } } } }), supports: true },
];
function captured(fn) { try { return { result: fn() ?? null }; } catch (error) { return { error: error.message }; } }
const grammars = grammarInputs.map(input => ({ input, expected: captured(() => constrained.resolveGrammarConstrainedSampling(input.tool, input.supports)) }));
const propertiesInputs = [
  { name: "supported", tools: [a, grammar(), b], compat: { supportsOpenAIGrammarTools: true } },
  { name: "unsupported", tools: [grammar()], compat: {} },
  { name: "same_name_latest_input", tools: [grammar(), grammar({ parameters: { type: "object", required: ["code"], properties: { code: { type: "string" } } } })], compat: { supportsOpenAIGrammarTools: true } },
  { name: "invalid_errors", tools: [grammarInputs[4].tool], compat: { supportsOpenAIGrammarTools: true } },
];
const properties = propertiesInputs.map(input => ({ input, expected: captured(() => Object.fromEntries(constrained.createGrammarToolInputProperties(input.tools, !!input.compat.supportsOpenAIGrammarTools))) }));
const conversionInputs = [
  { name: "plain", tools: [a, b], compat: {} },
  { name: "strict_prefer", tools: [tool("read", { constrainedSampling: { type: "json_schema", strict: "prefer" } })], compat: {} },
  { name: "strict_required_supported", tools: [tool("read", { constrainedSampling: { type: "json_schema", strict: "require" } })], compat: {} },
  { name: "strict_prefer_unsupported", tools: [tool("read", { constrainedSampling: { type: "json_schema", strict: "prefer" } })], compat: { supportsStrictMode: false } },
  { name: "strict_require_unsupported_errors", tools: [tool("read", { constrainedSampling: { type: "json_schema", strict: "require" } })], compat: { supportsStrictMode: false } },
  { name: "strict_prefer_invalid_falls_back", tools: [tool("read", { parameters: { type: "object", properties: { x: { type: "string" } }, additionalProperties: true }, constrainedSampling: { type: "json_schema", strict: "prefer" } })], compat: {} },
  { name: "grammar_supported", tools: [grammar(), a], compat: { supportsOpenAIGrammarTools: true } },
  { name: "grammar_unsupported_function_fallback", tools: [grammar()], compat: { supportsOpenAIGrammarTools: false } },
  { name: "grammar_regex", tools: [grammarInputs[2].tool], compat: { supportsOpenAIGrammarTools: true } },
  { name: "grammar_invalid_errors", tools: [grammarInputs[4].tool], compat: { supportsOpenAIGrammarTools: true } },
];
let fetchCalls = 0;
const forbiddenFetch = async () => { fetchCalls++; throw new Error("Forbidden offline oracle HTTP request"); };
const conversions = [];
for (const input of conversionInputs) {
  for (const api of ["openai-completions", "openai-responses"]) {
    let expected;
    if (api === "openai-responses") {
      expected = captured(() => responses.convertResponsesTools(input.tools, input.compat));
    } else {
      const model = { ...MODELS.openai["gpt-4.1"], api, compat: { ...MODELS.openai["gpt-4.1"].compat, ...input.compat } };
      let payload;
      const reply = await completions.streamSimple(model, { messages: [system({ toolsAdded: input.tools }), user] }, { apiKey: "sk-offline", fetch: forbiddenFetch, maxRetries: 0, onPayload: params => { payload = params; throw new Error("OFFLINE_PAYLOAD_CAPTURED"); } }).result();
      expected = payload ? { result: payload.tools ?? [] } : { error: reply.errorMessage };
    }
    conversions.push({ input: { ...input, api }, expected });
  }
  for (const defaultStrict of [false, true, null]) {
    const extra = { ...input, api: "openai-responses", toolSearchResult: true, defaultStrict };
    const expected = captured(() => responses.convertResponsesTools(input.tools, { ...input.compat, toolSearchResult: true, strict: defaultStrict }));
    conversions.push({ input: extra, expected });
  }
}
const argumentsInputs = [
  { name: "valid", toolName: "code", arguments: { input: "x\n😊" }, inputProperty: "input" },
  { name: "empty", toolName: "code", arguments: { input: "" }, inputProperty: "input" },
  { name: "missing", toolName: "code", arguments: {}, inputProperty: "input" },
  { name: "wrong_type", toolName: "code", arguments: { input: 7 }, inputProperty: "input" },
];
const argumentsCases = argumentsInputs.map(input => ({ input, expected: captured(() => constrained.getGrammarToolInput(input.toolName, input.arguments, input.inputProperty)) }));
const deltaInputs = [
  { name: "unicode_escaping", inputProperty: "in\"put", steps: [["", false], ["a\n", false], ["a\n😊\\\"", false], ["a\n😊\\\"", true], ["a\n😊\\\"", true]] },
  { name: "empty_close", inputProperty: "input", steps: [["", true], ["", true]] },
  { name: "non_monotonic", inputProperty: "input", steps: [["abc", false], ["ab", false]] },
  { name: "changed_after_close", inputProperty: "input", steps: [["abc", true], ["abcd", true]] },
  { name: "closed_without_close", inputProperty: "input", steps: [["abc", true], ["abc", false]] },
];
const deltas = deltaInputs.map(input => { const buffer = { input: "", started: false, closed: false }; const expected = input.steps.map(([value, close]) => ({ ...captured(() => constrained.appendGrammarToolInputJsonDelta(buffer, input.inputProperty, value, close)), buffer: structuredClone(buffer) })); return { input, expected }; });
if (fetchCalls) throw new Error(`Forbidden HTTP fetch count: ${fetchCalls}`);
const files = ["packages/ai/src/utils/transcript.ts", "packages/ai/src/api/constrained-sampling.ts", "packages/ai/src/api/openai-completions.ts", "packages/ai/src/api/openai-responses-shared.ts"];
const source_sha256 = Object.fromEntries(files.map(name => [name, createHash("sha256").update(readFileSync(path.join(root, name))).digest("hex")]));
console.log(JSON.stringify({ baseline: `v1.4.0@${commit}`, method: "Actual exported original transcript/constrained/Responses helpers; original Completion streamSimple captures tools via onPayload before any fetch. No network/account/paid model.", source_sha256, fetchCalls, resolutions, declarations, supports, grammars, properties, conversions, arguments: argumentsCases, deltas }, null, 2));
