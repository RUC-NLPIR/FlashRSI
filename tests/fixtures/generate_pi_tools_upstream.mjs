// Offline oracle: imports the pinned original TypeScript, never the native port.
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import os from "node:os";
const root = process.env.PI_REFERENCE_SOURCE;
if (!root) throw new Error("PI_REFERENCE_SOURCE is required");
globalThis.fetch = async () => { throw new Error("Network disabled in tool oracle"); };
process.env.PI_OFFLINE = "1";
const { validateToolArguments } = await import(path.join(root, "packages/ai/src/utils/validation.ts"));
const tools = {}, manifest = {}, sources = {};
for (const name of ["read", "bash", "edit", "write", "grep", "find", "ls"]) {
  const source = `packages/coding-agent/src/core/tools/${name}.ts`;
  const mod = await import(path.join(root, source));
  const title = name[0].toUpperCase() + name.slice(1);
  tools[name] = mod[`create${title}ToolDefinition`](process.cwd());
  manifest[name] = {
    description: tools[name].description,
    parameters: tools[name].parameters,
    ...mod[`${name}ToolSystemPromptContribution`],
  };
  sources[source] = createHash("sha256").update(fs.readFileSync(path.join(root, source))).digest("hex");
}
const cases = [
  ["write-number", "write", {path:"note.txt",content:123}],
  ["write-bool", "write", {path:true,content:false}],
  ["write-null", "write", {path:"note.txt",content:null}],
  ["write-object-path", "write", {path:{bad:1},content:"x"}],
  ["write-array-content", "write", {path:"note.txt",content:[1,2]}],
  ["write-missing", "write", {}],
  ["write-extra", "write", {path:"note.txt",content:"x",unexpected:1}],
  ["read-null-optionals", "read", {path:"note.txt",offset:null,limit:null}],
  ["read-string-numbers", "read", {path:"note.txt",offset:"1.5",limit:"0x10"}],
  ["read-bool-number", "read", {path:"note.txt",offset:true,limit:false}],
  ["read-empty-number", "read", {path:"note.txt",offset:"",limit:" "}],
  ["read-bad-number", "read", {path:"note.txt",offset:"one"}],
  ["read-object", "read", null],
  ["read-array", "read", []],
  ["read-missing", "read", {offset:2}],
  ["grep-bools", "grep", {pattern:12,ignoreCase:"true",literal:"false",limit:"0"}],
  ["grep-numeric-bools", "grep", {pattern:"x",ignoreCase:1,literal:0}],
  ["grep-string-numeric-bools", "grep", {pattern:"x",ignoreCase:"1",literal:"0"}],
  ["grep-invalid-bools", "grep", {pattern:"x",ignoreCase:"yes",literal:2}],
  ["edit-single-object", "edit", {path:"note.txt",edits:{oldText:"a",newText:"b"}}],
  ["edit-json-array", "edit", {path:"note.txt",edits:'[{"oldText":"a","newText":"b"}]'}],
  ["edit-json-object", "edit", {path:"note.txt",edits:'{"oldText":"a","newText":"b"}'}],
  ["edit-legacy", "edit", {path:"note.txt",oldText:"a",newText:"b"}],
  ["edit-combined", "edit", {path:"note.txt",edits:[{oldText:"c",newText:"d"}],oldText:"a",newText:"b"}],
  ["edit-coercion", "edit", {path:8,edits:[{oldText:12,newText:false,extra:1}]}],
  ["edit-invalid-json", "edit", {path:"note.txt",edits:"{"}],
  ["edit-missing-fields", "edit", {path:"note.txt",edits:[{}]}],
  ["edit-empty", "edit", {path:"note.txt",edits:[]}],
  ["bash-empty", "bash", {command:"",timeout:0}],
  ["bash-negative", "bash", {command:"printf x",timeout:-1}],
];
const validation = cases.map(([name, tool, original]) => {
  const args = structuredClone(original);
  try {
    const prepared = tools[tool].prepareArguments ? tools[tool].prepareArguments(args) : args;
    return {name,tool,arguments:original,result:validateToolArguments(tools[tool],{name:tool,arguments:prepared})};
  } catch (error) { return {name,tool,arguments:original,error:error.message}; }
});
const png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==";
const executionInputs = [
  ["read-plain", "read", {path:"note.txt"}],
  ["read-window", "read", {path:"note.txt",offset:2,limit:1}],
  ["read-zero-limit", "read", {path:"note.txt",limit:0}],
  ["read-fractional", "read", {path:"note.txt",offset:1.7,limit:1.7}],
  ["read-negative-limit", "read", {path:"note.txt",limit:-1}],
  ["read-offset-end", "read", {path:"note.txt",offset:99}],
  ["read-image-disguised", "read", {path:"picture.dat"}],
  ["read-fake-extension", "read", {path:"fake.png"}],
  ["read-invalid-image", "read", {path:"bad.jpg"}],
  ["read-image-no-vision", "read", {path:"picture.dat"}, {model:{input:["text"]}}],
  ["read-missing", "read", {path:"missing.txt"}],
  ["read-directory", "read", {path:"nested"}],
  ["write-coerced", "write", {path:"output.txt",content:123}],
  ["edit-coerced", "edit", {path:"note.txt",edits:[{oldText:"alpha",newText:false}]}],
  ["bash-empty", "bash", {command:""}],
  ["bash-stdout-stderr", "bash", {command:"printf first; sleep 0.03; printf second >&2; sleep 0.03; printf third"}],
  ["bash-nonzero", "bash", {command:"printf failed >&2; exit 7"}],
  ["bash-timeout-partial", "bash", {command:"printf before; sleep 1; printf after",timeout:0.05}],
  ["bash-zero-timeout", "bash", {command:"printf x",timeout:0}],
  ["bash-negative-timeout", "bash", {command:"printf x",timeout:-1}],
  ["bash-excessive-timeout", "bash", {command:"printf x",timeout:2147483.648}],
  ["bash-signal-exit", "bash", {command:"kill -TERM $$"}],
  ["bash-lines-spill", "bash", {command:"i=0; while [ $i -lt 2002 ]; do printf '%s\\n' $i; i=$((i+1)); done"}],
  ["bash-bytes-spill", "bash", {command:"head -c 51210 /dev/zero | tr '\\000' x"}],
  ["grep-limit-zero", "grep", {pattern:"a",path:"note.txt",limit:0}],
  ["grep-single-context", "grep", {pattern:"beta",path:"note.txt",context:1}],
  ["ls-zero", "ls", {path:"nested",limit:0}],
];
const execution = [];
for (const [name,tool,original,context] of executionInputs) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), "pi-tools-oracle-"));
  const files = {"note.txt":Buffer.from("alpha\nbeta\ngamma\n"),"picture.dat":Buffer.from(png,"base64"),
    "fake.png":Buffer.from("plain text\n"),"bad.jpg":Buffer.from([255,216,255,0]),"nested/a.txt":Buffer.from("a\n")};
  for (const [relative,bytes] of Object.entries(files)) {fs.mkdirSync(path.dirname(path.join(cwd,relative)),{recursive:true});fs.writeFileSync(path.join(cwd,relative),bytes);}
  const mod = await import(path.join(root,`packages/coding-agent/src/core/tools/${tool}.ts`));
  const definition = mod[`create${tool[0].toUpperCase()+tool.slice(1)}ToolDefinition`](cwd);
  let actual;
  try {
    let args = structuredClone(original);
    if (definition.prepareArguments) args=definition.prepareArguments(args);
    args=validateToolArguments(definition,{name:tool,arguments:args});
    const output=await definition.execute("oracle",args,undefined,undefined,context);
    actual={content:output.content,details:output.details??{},is_error:!!output.isError};
    if (output.details?.fullOutputPath) {
      const bytes=fs.readFileSync(output.details.fullOutputPath);
      actual.spill={size:bytes.length,sha256:createHash("sha256").update(bytes).digest("hex")};
      actual=JSON.parse(JSON.stringify(actual).split(output.details.fullOutputPath).join("<OUTPUT>"));
      fs.unlinkSync(output.details.fullOutputPath);
    }
  } catch(error) {actual={content:[{type:"text",text:error.message}],details:{},is_error:true};}
  actual=JSON.parse(JSON.stringify(actual).split(cwd).join("<WORKDIR>"));
  execution.push({name,tool,arguments:original,context,files:Object.fromEntries(Object.entries(files).map(([p,b])=>[p,b.toString("base64")])),result:actual});
  fs.rmSync(cwd,{recursive:true,force:true});
}
const result = {baseline:{version:"1.4.0",commit:"4a080252f06caf63a525d7873c5d94d3c23887e0",sources},manifest,validation,execution};
const destination = process.argv[2] || "tests/fixtures/pi_tool_contract_upstream.json";
fs.writeFileSync(destination, JSON.stringify(result,null,2)+"\n");
if (process.argv[3]) fs.writeFileSync(process.argv[3],JSON.stringify(manifest,null,2)+"\n");
console.log(JSON.stringify({destination,cases:validation.length}));
