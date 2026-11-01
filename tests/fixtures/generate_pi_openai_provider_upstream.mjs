/** Offline request-body oracle: original pinned OpenAI provider streamSimple.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 *   tests/fixtures/generate_pi_openai_provider_upstream.mjs > tests/fixtures/pi_openai_provider_upstream.json
 * onPayload captures the original body then throws; both custom and global fetch
 * reject as a second guard. No network, model generation, or paid requests.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root=process.env.PI_REFERENCE_SOURCE;
const deps=process.env.PI_REFERENCE_DEPS;
const commit="4a080252f06caf63a525d7873c5d94d3c23887e0";
if(execFileSync("git",["-C",root,"rev-parse","HEAD"],{encoding:"utf8"}).trim()!==commit) throw new Error("Wrong Pi source revision");
const releaseRoot=path.join(deps,"@earendil-works/pi-ai");
const release=JSON.parse(readFileSync(path.join(releaseRoot,"package.json")));
if(release.version!=="1.4.0") throw new Error("Wrong hydrated Pi model metadata version");
const {MODELS}=await import(pathToFileURL(path.join(releaseRoot,"dist/models.generated.js")).href);
const importSource=name=>import(pathToFileURL(path.join(root,name)).href);
const providers={
  "openai-completions":await importSource("packages/ai/src/api/openai-completions.ts"),
  "openai-responses":await importSource("packages/ai/src/api/openai-responses.ts"),
};
const zero={input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
const text=value=>({type:"text",text:value});
const user=value=>({role:"user",content:value,timestamp:1});
const image={type:"image",mimeType:"image/png",data:"iVBORw0KGgo="};
const tool={name:"read",description:"Read a fixture file",parameters:{type:"object",properties:{path:{type:"string"}},required:["path"],additionalProperties:false}};
const tool2={...tool,name:"other",description:"Another fixture tool"};
const system=(extra={})=>({role:"system",content:"system prompt",timestamp:0,...extra});
const base=()=>[system(),user("hello")];
const assistant=(content,extra={})=>({role:"assistant",content,usage:zero,stopReason:"stop",api:"openai-responses",provider:"openai",model:"gpt-5",timestamp:2,...extra});
const call=(id="call_a|fc_a",name="read")=>({type:"toolCall",id,name,arguments:{path:"fixture.txt"}});
const result=(id="call_a|fc_a",content=[text("read result")])=>({role:"toolResult",toolCallId:id,toolName:"read",content,isError:false,timestamp:3});
const inputs=[
  {name:"completions_gpt41_plain",id:"gpt-4.1",api:"openai-completions"},
  {name:"completions_gpt41_tools",id:"gpt-4.1",api:"openai-completions",messages:[system({toolsAdded:[tool]}),user("read")],maxTokens:100,temperature:0.2},
  ...["high","off","xhigh"].map(reasoning=>({name:`completions_gpt5_${reasoning}`,id:"gpt-5",api:"openai-completions",reasoning})),
  ...["high","off"].map(reasoning=>({name:`completions_deepseek_${reasoning}`,provider:"deepseek",id:"deepseek-flash",api:"openai-completions",reasoning})),
  ...["high","off","xhigh"].map(reasoning=>({name:`responses_gpt5_${reasoning}`,id:"gpt-5",api:"openai-responses",reasoning})),
  {name:"responses_gpt41_plain",id:"gpt-4.1",api:"openai-responses"},
  {name:"responses_cap_one_has_minimum_16",id:"gpt-5",api:"openai-responses",reasoning:"high",maxTokens:1,overrides:{contextWindow:30}},
  ...["openai-completions","openai-responses"].map(api=>({name:`interrupted_calls_${api}`,id:"gpt-5",api,reasoning:"high",messages:[system({toolsAdded:[tool]}),user("read"),assistant([call()],{api}),user("continue after interrupted tool")]})),
  {name:"responses_encrypted_reasoning_text_signature_pairs",id:"gpt-5",api:"openai-responses",reasoning:"high",messages:[
    system({toolsAdded:[tool]}),user("read"),assistant([
      {type:"thinking",thinking:"reason",thinkingSignature:JSON.stringify({id:"rs_fixture",type:"reasoning",summary:[{type:"summary_text",text:"reason"}],encrypted_content:"encrypted-fixture"})},
      {type:"text",text:"reading",textSignature:JSON.stringify({v:1,id:"msg_fixture",phase:"commentary"})},
      call(),
    ]),result(),user("continue"),
  ]},
  {name:"responses_multiple_text_blocks_without_signature",id:"gpt-5",api:"openai-responses",messages:[system(),user("first"),assistant([text("one"),text("two")]),user("next")]},
  {name:"responses_cross_provider_id_pair",id:"gpt-5",api:"openai-responses",messages:[system(),user("read"),assistant([call("call|item with @symbols")],{provider:"another",api:"openai-completions",model:"other"}),result("call|item with @symbols"),user("next")]},
  {name:"completions_distinct_response_items_share_call_prefix",id:"gpt-4.1",api:"openai-completions",messages:[system(),user("read"),assistant([call("shared|fc_one"),call("shared|fc_two")]),result("shared|fc_one"),result("shared|fc_two"),user("next")]},
  {name:"completions_long_response_item_id_hash",id:"gpt-4.1",api:"openai-completions",messages:[system(),user("read"),assistant([call("call_"+"a".repeat(60)+"|fc_"+"b".repeat(80))]),result("call_"+"a".repeat(60)+"|fc_"+"b".repeat(80)),user("next")]},
  {name:"responses_same_provider_different_model_id_pair",id:"gpt-5",api:"openai-responses",messages:[system(),user("read"),assistant([call()],{model:"gpt-4.1"}),result(),user("next")]},
  ...["openai-completions","openai-responses"].map(api=>({name:`native_user_and_tool_images_${api}`,id:"gpt-4.1",api,messages:[system({toolsAdded:[tool]}),user([text("look"),image]),assistant([call("call_image")],{model:"gpt-4.1",api}),result("call_image",[text("image result"),image]),user("describe")]})),
  {name:"completions_multiple_tool_images_group_after_all_results",id:"gpt-4.1",api:"openai-completions",messages:[system({toolsAdded:[tool]}),user("read both"),assistant([call("image_one"),call("image_two")],{model:"gpt-4.1",api:"openai-completions"}),result("image_one",[image]),result("image_two",[text("second"),image]),user("next")]},
  {name:"completions_sections_and_tools_update",id:"gpt-5",api:"openai-completions",reasoning:"high",messages:[system({sections:{goal:"initial",remove:"old"},toolsAdded:[tool]}),user("first"),assistant([text("done")],{api:"openai-completions"}),{role:"system",content:"updated prompt",sections:{goal:"new",remove:null},toolsRemoved:[{name:"read"}],toolsAdded:[tool2],timestamp:3},user("next")]},
  {name:"responses_sections_and_tools_update",id:"gpt-5",api:"openai-responses",reasoning:"high",messages:[system({sections:{goal:"initial",remove:"old"},toolsAdded:[tool]}),user("first"),assistant([text("done")]),{role:"system",content:"updated prompt",sections:{goal:"new",remove:null},toolsRemoved:[{name:"read"}],toolsAdded:[tool2],timestamp:3},user("next")]},
  {name:"deepseek_native_system_update",provider:"deepseek",id:"deepseek-v4-pro",api:"openai-completions",reasoning:"high",messages:[system({sections:{goal:"initial"}}),user("first"),assistant([text("done")],{provider:"deepseek",api:"openai-completions",model:"deepseek-v4-pro"}),{role:"system",content:"updated prompt",sections:{goal:"new"},timestamp:3},user("next")]},
  {name:"deepseek_same_model_reasoning_content_replay",provider:"deepseek",id:"deepseek-flash",api:"openai-completions",reasoning:"high",messages:[system(),user("first"),assistant([{type:"thinking",thinking:"first thought",thinkingSignature:"reasoning_content"},{type:"thinking",thinking:"second thought",thinkingSignature:"reasoning_content"},text("done")],{provider:"deepseek",api:"openai-completions",model:"deepseek-flash"}),user("next")]},
  {name:"deepseek_nonvision_images_downgrade",provider:"deepseek",id:"deepseek-v4-pro",api:"openai-completions",reasoning:"high",messages:[system(),user([image,image,text("look")]),assistant([call("image")],{provider:"deepseek",api:"openai-completions",model:"deepseek-v4-pro"}),result("image",[image,image]),user("next")]},
  ...["openai-completions","openai-responses"].map(api=>({name:`error_and_aborted_assistant_filter_${api}`,id:"gpt-4.1",api,messages:[system(),user("first"),assistant([text("partial"),call("skip")],{model:"gpt-4.1",api,stopReason:"error"}),assistant([text("aborted"),call("also-skip")],{model:"gpt-4.1",api,stopReason:"aborted"}),user("next")]})),
];
const cases=[];
let fetchCalls=0;
const forbiddenFetch=async()=>{fetchCalls++;throw new Error("Forbidden: oracle must never perform an HTTP request");};
const originalFetch=globalThis.fetch;
globalThis.fetch=forbiddenFetch;
try {
  for(const input of inputs){
    const provider=input.provider??"openai";
    const catalog=MODELS[provider]?.[input.id];
    if(!catalog) throw new Error(`Missing release catalog model ${provider}/${input.id}`);
    const model={...structuredClone(catalog),api:input.api,...input.overrides};
    const messages=structuredClone(input.messages??base());
    let payload;
    // The original Responses provider treats non-sk credentials on OpenAI's
    // default URL as ChatGPT tokens and omits API-only fields. This oracle
    // exercises ordinary API-key mode with a deliberately fake sk- value.
    const options={apiKey:"sk-offline-fixture",fetch:forbiddenFetch,maxRetries:0,
      ...(input.reasoning?{reasoning:input.reasoning}:{}),
      ...(input.maxTokens===undefined?{}:{maxTokens:input.maxTokens}),
      ...(input.temperature===undefined?{}:{temperature:input.temperature}),
      onPayload:body=>{payload=JSON.parse(JSON.stringify(body));throw new Error("OFFLINE_PAYLOAD_CAPTURED");},
    };
    const reply=await providers[input.api].streamSimple(model,{messages},options).result();
    if(!payload || !reply.errorMessage?.includes("OFFLINE_PAYLOAD_CAPTURED")) throw new Error(`${input.name}: expected offline interception; ${reply.errorMessage}`);
    const config={llm:{model_name:`${provider}/${input.id}`,model_api:input.api,base_url:model.baseUrl,api_key:"sk-offline-fixture"},
      ...(input.maxTokens===undefined?{}:{max_tokens:input.maxTokens}),
      ...(input.temperature===undefined?{}:{temperature:input.temperature}),
      ...(input.overrides?.contextWindow===undefined?{}:{context_window:input.overrides.contextWindow}),
    };
    cases.push({input:{name:input.name,config,api:input.api,reasoning:input.reasoning??null,context:messages,model},expected:{payload}});
  }
} finally {globalThis.fetch=originalFetch;}
if(fetchCalls!==0) throw new Error(`Forbidden HTTP fetch count: ${fetchCalls}`);
const sources=["packages/ai/src/api/openai-completions.ts","packages/ai/src/api/openai-responses.ts","packages/ai/src/api/openai-responses-shared.ts","packages/ai/src/api/simple-options.ts","packages/ai/src/api/transform-messages.ts","packages/ai/src/utils/transcript.ts","packages/ai/src/utils/text.ts"];
const source_sha256=Object.fromEntries(sources.map(name=>[name,createHash("sha256").update(readFileSync(path.join(root,name))).digest("hex")]));
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:"Unmodified original streamSimple and request builders; onPayload captures then throws, custom/global fetch forbidden. Matching release model metadata only. No model generation or network.",release:{"@earendil-works/pi-ai":release.version},source_sha256,fetchCalls,cases},null,2));
