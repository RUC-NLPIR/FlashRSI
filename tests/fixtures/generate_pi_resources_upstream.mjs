/** Offline oracle: execute original pinned Pi prompt and resource functions. */
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync, realpathSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
const source = process.env.PI_REFERENCE_SOURCE;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", source, "rev-parse", "HEAD"], { encoding: "utf8" }).trim() !== commit) throw new Error("Wrong source");
const original = file => import(pathToFileURL(path.join(source, "packages/coding-agent/src", file)).href);
const prompt = await original("core/system-prompt.ts");
const skillModule = await original("core/skills.ts");
const templates = await original("core/prompt-templates.ts");
const frontmatter = await original("utils/frontmatter.ts");
const manifest = JSON.parse(readFileSync(new URL("../../flashrsi/agents/pi_agent/runtime/pi_native/tool_manifest.json", import.meta.url)));
const base = { cwd: "/task", toolSnippets: Object.fromEntries(Object.entries(manifest).map(([name, item]) => [name, item.snippet])), toolGuidelines: Object.fromEntries(Object.entries(manifest).map(([name, item]) => [name, item.guidelines || []])) };
const normalize = value => JSON.parse(JSON.stringify(value).replaceAll(realpathSync(path.join(source, "packages/coding-agent")), "<REFERENCE>").replaceAll(path.join(source, "packages/coding-agent"), "<REFERENCE>"));
const sampleSkill = { name: "a<&", description: "document <commands>", filePath: "/skill/SKILL.md", disableModelInvocation: false };
const definitions = [
  ["default", {}], ["none", { selectedTools: [] }], ["search_tools", { selectedTools: ["grep", "find", "ls", "read"] }],
  ["reordered", { selectedTools: ["write", "bash", "edit", "read"] }], ["unknown", { selectedTools: ["unknown"] }],
  ["custom", { customPrompt: "Exact custom preamble\n", appendSystemPrompt: "  appended\n" }],
  ["custom_whitespace", { customPrompt: " " }], ["context", { contextFiles: [{ path: "/task/AGENTS.md", content: "rules\n" }] }],
  ["skill_read", { skills: [sampleSkill] }], ["skill_bash", { selectedTools: ["bash"], skills: [sampleSkill] }],
  ["skill_hidden", { hiddenTools: ["read", "bash"], skills: [sampleSkill] }], ["skill_no_reader", { selectedTools: [], skills: [sampleSkill] }],
  ["disabled_skill", { skills: [{ ...sampleSkill, disableModelInvocation: true }] }],
  ["rules_dedupe", { toolGuidelines: { read: ["  same  ", "same", ""] }, promptGuidelines: ["same", "extra"] }],
  ["sections_override", { sections: { cwd: "custom cwd", rules: "custom rules", extra: "kept", empty: "" } }],
  ["forced", { forceSystemPrompt: "opaque replacement\n" }], ["invalid_section", { sections: { "BAD NAME": "invalid" } }],
];
const cases = definitions.map(([name, extra]) => {
  const options = { ...base, ...extra };
  try { return { name, options, state: normalize(prompt.buildSystemPromptState(options)), text: normalize(prompt.buildSystemPrompt(options)) }; }
  catch (error) { return { name, options, error: error.message }; }
});
const patches = [[{}, { preamble: "a", cwd: "b" }], [{ a: "same", b: "remove" }, { a: "same", c: "new" }], [{ a: "same" }, { a: "same" }]].map(([previous,current]) => ({ previous, current, expected: prompt.diffSystemPromptSections(previous,current) ?? null }));
const fm = ["plain\r\nbody\r\n", "---\ndescription: yes\n---\n body \n", "---\ndescription: on\n---\nbody", "---\nname: 0123\n---\nbody", "---\ndisabled: false\n---\nbody", "---\ndescription: spaced\n---\n\n  body  \n"].map(raw => ({raw, expected: frontmatter.parseFrontmatter(raw)}));
const temp = mkdtempSync(path.join(tmpdir(), "pi-resource-oracle-"));
const skillFiles = {
  ".gitignore": "ignored/\n*.skip.md\n",
  ".ignore": "z-ignore/\n",
  ".fdignore": "from-fd/\n",
  "a-first.md": "---\nname: first\ndescription: loose root skill\n---\nbody",
  "z-last.md": "---\nname: last\ndescription: loose root skill\n---\nbody",
  "root.skip.md": "---\nname: skipped\ndescription: ignored root skill\n---\nbody",
  "ignored/SKILL.md": "---\nname: ignored\ndescription: ignored directory\n---\nbody",
  "z-ignore/SKILL.md": "---\nname: ignored\ndescription: ignored directory\n---\nbody",
  "from-fd/SKILL.md": "---\nname: ignored\ndescription: ignored directory\n---\nbody",
  "nested/.ignore": "hidden/\n",
  "nested/hidden/SKILL.md": "---\nname: ignored\ndescription: ignored nested directory\n---\nbody",
  "nested/visible/SKILL.md": "---\nname: visible\ndescription: visible nested directory\n---\nbody",
  "bad-name/SKILL.md": "---\nname: Bad_NAME\ndescription: ' padded description '\ndisable-model-invocation: 'false'\n---\nSkill body\n",
  "long/SKILL.md": "---\nname: long\ndescription: '" + "x".repeat(1025) + "'\n---\nbody",
  "missing/SKILL.md": "---\nname: missing\n---\nbody",
  "disabled/SKILL.md": "---\nname: disabled\ndescription: hidden\ndisable-model-invocation: true\n---\nbody",
};
let loaded;
try {
  for (const [relative, content] of Object.entries(skillFiles)) { const target = path.join(temp, relative); mkdirSync(path.dirname(target), {recursive:true}); writeFileSync(target, content); }
  const result = skillModule.loadSkillsFromDir({ dir: temp, source: "user" });
  loaded = result.skills.map(skill => ({name:skill.name, description:skill.description, path:path.relative(temp,skill.filePath), disable_model_invocation:skill.disableModelInvocation}));
} finally { rmSync(temp,{recursive:true,force:true}); }
console.log(JSON.stringify({ commit, cases, patches, frontmatter: fm, skills: { files: skillFiles, expected: loaded } }, null, 2));
