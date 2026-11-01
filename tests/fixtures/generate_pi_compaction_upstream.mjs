/**
 * Offline oracle: execute original pinned Pi source, never a rewritten mock.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 *   ./tests/fixtures/generate_pi_compaction_upstream.mjs > ./tests/fixtures/pi_compaction_upstream.json
 * Node 24 strips source TypeScript types. npm dependencies are development-only.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";
const root = process.env.PI_REFERENCE_SOURCE;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim() !== commit) throw new Error("Wrong Pi source revision");
if (process.argv.includes("--model-limits")) {
  // Generated provider JSON is intentionally absent from the Git checkout.
  // Read the matching 1.4.0 release's hydrated, offline model catalog.
  const packageRoot = path.join(process.env.PI_REFERENCE_DEPS, "@earendil-works/pi-ai");
  if (JSON.parse(readFileSync(path.join(packageRoot, "package.json"))).version !== "1.4.0") throw new Error("Wrong model catalog version");
  const { MODELS } = await import(pathToFileURL(path.join(packageRoot, "dist/models.generated.js")).href);
  const limits = {};
  for (const [provider, models] of Object.entries(MODELS)) {
    for (const model of Object.values(models)) {
      // Preserve complete metadata: provider conversion, native system/tool
      // changes, image support, sampling and usage costs all depend on it.
      limits[`${provider}/${model.id}`] = model;
    }
  }
  console.log(JSON.stringify(limits, null, 2));
  process.exit(0);
}
const source = name => import(pathToFileURL(path.join(root, name)).href);
const c = await source("packages/coding-agent/src/core/compaction/compaction.ts");
const utils = await source("packages/coding-agent/src/core/compaction/utils.ts");
const sessions = await source("packages/coding-agent/src/core/session-manager.ts");
const messages = await source("packages/coding-agent/src/core/messages.ts");
const ai = await import(pathToFileURL(path.join(process.env.PI_REFERENCE_DEPS, "@earendil-works/pi-ai/dist/index.js")).href);
const overflow = await source("packages/ai/src/utils/overflow.ts");
const zero = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
const user = text => ({ role: "user", content: text, timestamp: 1 });
const assistant = (content, extra = {}) => ({ role: "assistant", content, usage: zero,
  stopReason: "stop", api: "openai-completions", provider: "openai", model: "oracle", timestamp: 2, ...extra });
const text = value => ({ type: "text", text: value });
const call = (name, args, id = "call") => ({ type: "toolCall", id, name, arguments: args });
const chain = msgs => msgs.map((message, i) => ({ type: "message", id: `e${i}`, parentId: i ? `e${i - 1}` : null,
  timestamp: "2026-10-31T00:00:00.000Z", message }));
const system = { role: "system", content: "system", timestamp: 0 };
const history = chain([system, user("old request is long enough"), assistant([text("old done")]),
  user("current task"), assistant([text("current current current current")])]);
const toolHistory = chain([system, user("update the project"), assistant([call("read", { path: "a.py" })], {stopReason:"toolUse"}),
  {role:"toolResult",toolCallId:"call",toolName:"read",content:[text("A".repeat(80))],isError:false,timestamp:3},
  assistant([call("edit",{path:"a.py",oldText:"A",newText:"B"})],{stopReason:"toolUse"}),
  {role:"toolResult",toolCallId:"call",toolName:"edit",content:[text("B".repeat(80))],isError:false,timestamp:4},
  assistant([text("done")])]);
const incremental = [...history, {type:"compaction", id:"checkpoint",parentId:"e4",timestamp:"2026-10-31T00:00:01.000Z",
  summary:"previous summary",firstKeptEntryId:"e3",tokensBefore:100,details:{readFiles:["older.py"],modifiedFiles:["changed.py"]},systemMessage:system},
  {type:"message",id:"fresh",parentId:"checkpoint",timestamp:"2026-10-31T00:00:02.000Z",message:user("new work")},
  {type:"message",id:"fresh-answer",parentId:"fresh",timestamp:"2026-10-31T00:00:03.000Z",message:assistant([text("new answer")])}];
const cases = [
  {name:"whole_turn",entries:history,keep:11},
  {name:"split_turn",entries:history,keep:3},
  {name:"tool_result_keeps_call",entries:toolHistory,keep:4},
  {name:"trailing_large_tool_result_keeps_its_call",entries:toolHistory.slice(0,6),keep:4},
  {name:"incremental",entries:incremental,keep:5},
  {name:"tool_files",entries:[...toolHistory,...chain([user("next task"),assistant([text("latest")])]).map((e,i)=>({...e,id:`n${i}`,parentId:i?"n0":"e6"}))],keep:5},
  {name:"edited_projection",entries:[...history,{type:"context_edit",id:"edit",parentId:"e4",targetId:"e1",replacement:{content:"edited user"},timestamp:"2026-10-31T00:00:04.000Z"}],keep:11},
  {name:"system_replay",entries:chain([
    {...system,sections:{a:"retained section",b:"remove me"},toolsAdded:[{name:"read",description:"read",parameters:{type:"object"}}]},
    {...system,content:"extra instructions",sections:{b:null,c:"new section"},toolsRemoved:[{name:"read"}],toolsAdded:[{name:"write",description:"write",parameters:{type:"object"}}]},
    ...history.slice(1).map(e=>e.message)
  ]),keep:11},
  {name:"null_content",entries:chain([system,{role:"user",content:null,timestamp:1},assistant([text("old answer")]),user("current task"),assistant([text("current current current current")])]),keep:11},
  {name:"unicode_tool_slice",entries:chain([system,user("read file"),assistant([call("read",{path:"emoji.txt"})],{stopReason:"toolUse"}),
    {role:"toolResult",toolCallId:"call",toolName:"read",content:[text("x".repeat(1999)+"😊end")],isError:false,timestamp:3},
    user("next task"),assistant([text("next answer")])]),keep:7},
  {name:"stale_usage_after_compaction",entries:incremental.map(e=>e.id==="e4"?{...e,message:{...e.message,usage:{...zero,input:100000,totalTokens:100000}}}:e),keep:5},
  {name:"unicode_file_sort",entries:chain([system,user("read these"),assistant([call("read",{path:"\ue000.txt"}),call("read",{path:"😊.txt"}),call("read",{path:"a.txt"})],{stopReason:"toolUse"}),user("next task"),assistant([text("next answer")])]),keep:7},
  {name:"too_small",entries:chain([system,user("hi")]),keep:20000},
];
const model = {id:"oracle",name:"oracle",api:"openai-completions",provider:"openai",baseUrl:"http://oracle.invalid/v1",
  reasoning:false,input:["text"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:128000,maxTokens:4096};
const outputs=[];
for (const input of cases) {
  const settings={...c.DEFAULT_COMPACTION_SETTINGS,keepRecentTokens:input.keep};
  const prep=c.prepareCompaction(input.entries,settings);
  const requests=[];
  let count=0;
  const streamFn=(_model,context,options)=>{
    requests.push({messages:context.messages.map(({timestamp,...m})=>m),options:{cacheRetention:options.cacheRetention,hasSessionId:!!options.sessionId}});
    const stream=ai.createAssistantMessageEventStream();
    const message=assistant([text(`summary-${++count}`)]);
    queueMicrotask(()=>stream.push({type:"done",reason:"stop",message}));
    return stream;
  };
  const result=prep ? await c.compact(prep,model,"fixture-only",undefined,"preserve paths",undefined,undefined,streamFn) : null;
  const prepared=prep ? {...prep,fileOps:utils.computeFileLists(prep.fileOps)} : null;
  const systemAfter=ai.getCurrentSystemMessage(sessions.buildSessionProjection(input.entries).messages);
  if (systemAfter) delete systemAfter.timestamp;
  outputs.push({input,expected:{preparation:prepared,result,requests,systemAfter}});
}
const tokenMessages=[...history.map(e=>e.message),user("😊".repeat(5)),
 {role:"user",content:[{type:"image",data:"AA",mimeType:"image/png"},text("abc")]},
 {role:"system",content:"s",sections:{a:"section"},toolsAdded:[{name:"read",parameters:{}}]},
 assistant([text("valid")],{usage:{...zero,input:20,cacheRead:10,totalTokens:30}}),
 assistant([text("error")],{stopReason:"error",usage:{...zero,totalTokens:900}})];
const overflowCases=[
 {message:assistant([],{stopReason:"error",errorMessage:"prompt is too long: 200 tokens > 100 maximum"}),window:100},
 {message:assistant([],{stopReason:"error",errorMessage:"rate limit: too many tokens"}),window:100},
 {message:assistant([],{stopReason:"stop",usage:{...zero,input:101}}),window:100},
 {message:assistant([],{stopReason:"length",usage:{...zero,input:99,output:0}}),window:100},
 {message:assistant([],{stopReason:"length",usage:{...zero,input:10,output:2}}),window:100},
].map(input=>({input,overflow:overflow.isContextOverflow(input.message,input.window),recoverable:overflow.isRecoverableLength(input.message,4096)}));
const sourceFiles=["packages/coding-agent/src/core/compaction/compaction.ts","packages/coding-agent/src/core/compaction/utils.ts",
 "packages/coding-agent/src/core/session-manager.ts","packages/coding-agent/src/core/messages.ts","packages/ai/src/utils/overflow.ts"];
const source_sha256=Object.fromEntries(sourceFiles.map(name=>[name,createHash("sha256").update(readFileSync(path.join(root,name))).digest("hex")]));
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:"Original pinned TypeScript prepareCompaction + compact executed with offline fixed assistant responses; original session projection and overflow utilities.",source_sha256,
 cases:outputs,tokens:tokenMessages.map(message=>({message,expected:c.estimateTokens(message)})),
 context:{messages:tokenMessages,expected:c.estimateContextTokens(tokenMessages)},
 serialization:{messages:tokenMessages,expected:utils.serializeConversation(messages.convertToLlm(tokenMessages))},overflow:overflowCases},null,2));
