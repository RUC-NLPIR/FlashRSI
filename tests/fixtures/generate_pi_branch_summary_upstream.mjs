/** Development-only offline oracle, executing original Pi v1.4.0 TypeScript.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 *   ./tests/fixtures/generate_pi_branch_summary_upstream.mjs > ./tests/fixtures/pi_branch_summary_upstream.json
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";
const root = process.env.PI_REFERENCE_SOURCE;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim() !== commit) throw new Error("Wrong Pi source revision");
const source = name => import(pathToFileURL(path.join(root, name)).href);
const branch = await source("packages/coding-agent/src/core/compaction/branch-summarization.ts");
const utils = await source("packages/coding-agent/src/core/compaction/utils.ts");
const {SessionManager} = await source("packages/coding-agent/src/core/session-manager.ts");
const ai = await import(pathToFileURL(path.join(process.env.PI_REFERENCE_DEPS, "@earendil-works/pi-ai/dist/index.js")).href);
const zero = {input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
const text = value => ({type:"text",text:value});
const user = value => ({role:"user",content:value,timestamp:1});
const assistant = (content,extra={})=>({role:"assistant",content,usage:zero,stopReason:"stop",api:"openai-completions",provider:"openai",model:"oracle",timestamp:2,...extra});
const call = (name,args)=>({type:"toolCall",id:"call",name,arguments:args});
const stamp="2026-11-01T00:00:00.000Z";
const msg=(id,parentId,message)=>({type:"message",id,parentId,timestamp:stamp,message});
const system=msg("root",null,{role:"system",content:"system",timestamp:0});
const entries=[system,msg("old-user","root",user("explore a branch")),
 msg("old-tools","old-user",assistant([call("read",{path:"seen.py"}),call("write",{path:"written.py",content:"yes"})],{stopReason:"toolUse"})),
 msg("tool-result","old-tools",{role:"toolResult",toolCallId:"call",toolName:"write",content:[text("must be omitted".repeat(500))],isError:false,timestamp:3}),
 {type:"compaction",id:"compact","parentId":"tool-result",timestamp:stamp,summary:"important compacted history",firstKeptEntryId:"old-tools",tokensBefore:500},
 {type:"branch_summary",id:"nested",parentId:"compact",timestamp:stamp,fromId:"elsewhere",summary:"nested branch",details:{readFiles:["inherited.py"],modifiedFiles:["changed.py"]}},
 msg("old-leaf","nested",assistant([text("work done")]))];
const target=msg("target","root",assistant([text("the chosen branch")]));
const all=[...entries,target];
const model={id:"oracle",name:"oracle",api:"openai-completions",provider:"openai",baseUrl:"http://oracle.invalid/v1",reasoning:false,input:["text"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:128000,maxTokens:4096};
const inputs=[
 {name:"whole_branch",entries:entries.slice(1),budget:0,options:{}},
 {name:"budget_newest",entries:entries.slice(1),budget:5,options:{contextWindow:20,reserveTokens:15}},
 {name:"checkpoint_beyond_budget",entries:entries.slice(1),budget:15,options:{contextWindow:30,reserveTokens:15}},
 {name:"append_focus",entries:entries.slice(1),budget:0,options:{customInstructions:"track exact paths"}},
 {name:"replace_focus",entries:entries.slice(1),budget:0,options:{customInstructions:"only report status",replaceInstructions:true}},
 {name:"empty",entries:[{type:"label",id:"label",parentId:null,timestamp:stamp,targetId:"x",label:"hi"}],budget:0,options:{}},
 ...["length","error","aborted","toolUse"].map(reason=>({name:`failure_${reason}`,entries:entries.slice(1),budget:0,options:{},reason})),
 {name:"hook_files_ignored",entries:[{...entries[5],fromHook:true},msg("last","nested",assistant([text("done")]))],budget:0,options:{}},
];
const cases=[];
for(const input of inputs){
 const prep=branch.prepareBranchEntries(input.entries,input.budget);
 const requests=[];
 const streamFn=(_model,context,options)=>{
  requests.push({messages:context.messages.map(({timestamp,...m})=>m),options:{cacheRetention:options.cacheRetention,hasSessionId:!!options.sessionId}});
  const stream=ai.createAssistantMessageEventStream();
  const reason=input.reason??"stop";
  const message=assistant(reason==="toolUse"?[call("write",{path:"bad",content:"bad"})]:[text("branch checkpoint")],{stopReason:reason,...(reason==="error"?{errorMessage:"invalid request"}:{})});
  queueMicrotask(()=>stream.push({type:reason==="error"||reason==="aborted"?"error":"done",reason,message,...(reason==="error"||reason==="aborted"?{error:message}:{})}));
  return stream;
 };
 const {contextWindow,...options}=input.options;
 const result=await branch.generateBranchSummary(input.entries,{model:{...model,...(contextWindow?{contextWindow}:{})},apiKey:"fixture-only",signal:new AbortController().signal,streamFn,...options});
 cases.push({input,expected:{preparation:{...prep,fileOps:utils.computeFileLists(prep.fileOps)},result,requests}});
}
const manager=SessionManager.inMemory("/oracle",{},[{type:"session",version:3,id:"oracle",timestamp:stamp,cwd:"/oracle"},...all]);
const collections=[
 {oldLeafId:"old-leaf",targetId:"target"},
 {oldLeafId:"old-leaf",targetId:"old-user"},
 {oldLeafId:"old-leaf",targetId:"old-leaf"},
 {oldLeafId:null,targetId:"target"},
].map(input=>({input,expected:branch.collectEntriesForBranchSummary(manager,input.oldLeafId,input.targetId)}));
const sourceFiles=["packages/coding-agent/src/core/compaction/branch-summarization.ts","packages/coding-agent/src/core/compaction/compaction.ts","packages/coding-agent/src/core/compaction/utils.ts","packages/coding-agent/src/core/session-manager.ts"];
const source_sha256=Object.fromEntries(sourceFiles.map(name=>[name,createHash("sha256").update(readFileSync(path.join(root,name))).digest("hex")]));
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:"Original pinned TypeScript collectEntriesForBranchSummary, prepareBranchEntries and generateBranchSummary with offline fixed assistant responses; no paid requests.",source_sha256,cases,treeEntries:all,collections},null,2));
