/** Offline original-source oracle for OpenAI thinking, cache and affinity.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 * tests/fixtures/generate_pi_openai_options_upstream.mjs > tests/fixtures/pi_openai_options_upstream.json
 * All body capture stops before fetch. Header/cost cases use in-memory SSE
 * responses and never access HTTP, credentials, or a language model.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root=process.env.PI_REFERENCE_SOURCE;
const deps=process.env.PI_REFERENCE_DEPS;
const commit="4a080252f06caf63a525d7873c5d94d3c23887e0";
if(execFileSync("git",["-C",root,"rev-parse","HEAD"],{encoding:"utf8"}).trim()!==commit) throw new Error("Wrong source revision");
const releaseRoot=path.join(deps,"@earendil-works/pi-ai");
const release=JSON.parse(readFileSync(path.join(releaseRoot,"package.json")));
if(release.version!=="1.4.0") throw new Error("Wrong release metadata");
const {MODELS}=await import(pathToFileURL(path.join(releaseRoot,"dist/models.generated.js")).href);
const {clampThinkingLevel}=await import(pathToFileURL(path.join(releaseRoot,"dist/models.js")).href);
const source=name=>import(pathToFileURL(path.join(root,name)).href);
const providers={
  "openai-completions":await source("packages/ai/src/api/openai-completions.ts"),
  "openai-responses":await source("packages/ai/src/api/openai-responses.ts"),
};
const simple=await source("packages/ai/src/api/simple-options.ts");
const baseModel=(api,overrides={})=>({...structuredClone(MODELS.openai["gpt-5"]),
  api,provider:"fixture",baseUrl:"https://fixture.invalid/v1",reasoning:true,
  thinkingLevelMap:{off:"none",minimal:"minimal",low:"low",medium:"medium",high:"high",xhigh:"xhigh",max:"max"},
  ...overrides});
const messages=[{role:"system",content:"system",timestamp:0},{role:"user",content:"hello",timestamp:1}];
let networkCalls=0, fakeTransportCalls=0;
const forbiddenFetch=async()=>{networkCalls++;throw new Error("Forbidden network dispatch");};
const originalFetch=globalThis.fetch;
globalThis.fetch=forbiddenFetch;
const bodyCases=[],headerCases=[],costCases=[],cacheControlCases=[],budgetCases=[];
async function payload(model,options={},context=messages){
  let body;
  const result=await providers[model.api].streamSimple(model,{messages:context},{
    apiKey:"sk-offline-fixture",maxTokens:10000,maxRetries:0,fetch:forbiddenFetch,...options,
    onPayload:value=>{body=JSON.parse(JSON.stringify(value));throw new Error("OFFLINE_CAPTURE");},
  }).result();
  if(!body || !result.errorMessage?.includes("OFFLINE_CAPTURE")) throw new Error(`Capture failed: ${result.errorMessage}`);
  return body;
}
async function optionCase(name,compat,reasoning="high",extra={}){
  const {options={},modelOverrides={}}=extra;
  const model=baseModel("openai-completions",{compat,...modelOverrides});
  const body=await payload(model,{reasoning,...options});
  const expected={...body};
  for(const key of ["model","messages","stream","stream_options","max_tokens","max_completion_tokens","store","prompt_cache_key","prompt_cache_retention"]){delete expected[key];}
  const clamped=reasoning?clampThinkingLevel(model,reasoning):undefined;
  bodyCases.push({name,model,compat,level:clamped===undefined||clamped==="off"?null:clamped,
    ceiling:body.max_tokens??body.max_completion_tokens??model.maxTokens,
    thinking_budgets:options.thinkingBudgets??null,expected});
}
try{
  for(const form of ["openai","zai","qwen","qwen-chat-template","deepseek","openrouter","ant-ling","together","string-thinking"]){
    for(const level of ["high","off"]){
      await optionCase(`${form}_${level}`,{thinkingFormat:form,supportsReasoningEffort:true},level);
    }
  }
  for(const form of ["openai","zai","qwen","deepseek","openrouter","together","string-thinking"]){
    await optionCase(`${form}_off_null`,{thinkingFormat:form,supportsReasoningEffort:true},"off",{
      modelOverrides:{thinkingLevelMap:{...baseModel("openai-completions").thinkingLevelMap,off:null}},
    });
    await optionCase(`${form}_unset_off_null`,{thinkingFormat:form,supportsReasoningEffort:true},null,{
      modelOverrides:{thinkingLevelMap:{...baseModel("openai-completions").thinkingLevelMap,off:null}},
    });
  }
  await optionCase("ant_ling_unmapped_effort",{thinkingFormat:"ant-ling"},"high",{modelOverrides:{thinkingLevelMap:{off:"none"}}});
  const descriptors={literal:"keep",number:7,disabledLiteral:false,nullLiteral:null,
    enabled:{$var:"thinking.enabled"},effort:{$var:"thinking.effort"},budget:{$var:"thinking.budget"},
    onlyEnabled:{$var:"thinking.enabled",omitWhenOff:true},onlyEffort:{$var:"thinking.effort",omitWhenOff:true}};
  for(const form of ["chat-template","baseten"]){
    for(const level of ["high","off"]){
      await optionCase(`${form}_${level}`,{thinkingFormat:form,supportsReasoningEffort:true,
        [form==="chat-template"?"chatTemplateKwargs":"chatTemplateArgs"]:descriptors},level);
    }
  }
  await optionCase("chat_template_omits_all_off",{thinkingFormat:"chat-template",chatTemplateKwargs:{x:{$var:"thinking.budget"},y:{$var:"thinking.effort"}}},"off",{modelOverrides:{thinkingLevelMap:{off:null}}});
  await optionCase("budget_default_alias",{supportsThinkingTokenBudget:true},"high");
  for(const field of ["thinking_token_budget","thinking_budget","thinking_budget_tokens"]){
    await optionCase(`budget_${field}`,{thinkingTokenBudgetField:field},"medium",{options:{thinkingBudgets:{medium:6000}}});
  }
  await optionCase("budget_no_answer_room",{supportsThinkingTokenBudget:true},"high",{options:{maxTokens:1024}});
  await optionCase("budget_context_window_ceiling",{thinkingTokenBudgetField:"thinking_budget"},"high",{modelOverrides:{contextWindow:7000}});
  await optionCase("budget_xhigh_uses_high_custom",{supportsThinkingTokenBudget:true},"xhigh",{options:{maxTokens:20000,thinkingBudgets:{high:12000}}});
  await optionCase("budget_disabled_for_nonreasoning",{supportsThinkingTokenBudget:true},"high",{modelOverrides:{reasoning:false}});
  await optionCase("routing_empty_router",{openRouterRouting:{}},"off");
  await optionCase("routing_gateway_priority",{openRouterRouting:{order:["a","b"],allow_fallbacks:false},vercelGatewayRouting:{only:[],order:["b","a"]},vllmPriority:0},"off");
  for(const level of ["minimal","low","medium","high","xhigh","max"]){
    for(const budgets of [undefined,{high:12000,low:1500}]){
      for(const base of [undefined,1,1024,16000]){
        budgetCases.push({name:`budget_${level}_${JSON.stringify(budgets)}_${base}`,level,budgets:budgets??null,base:base??null,model_max:8192,
          expected_budget:simple.thinkingBudgetForLevel(level,budgets),expected_adjust:simple.adjustMaxTokensForThinking(base,8192,level,budgets)});
      }
    }
  }

  for(const api of ["openai-completions","openai-responses"]){
    for(const retention of ["none","short","long"]){
      for(const explicit of [false,true]){
        const model=baseModel(api,{provider:"openai",baseUrl:"https://api.openai.com/v1",
          compat:{supportsLongCacheRetention:true,supportsExplicitPromptCacheMode:explicit}});
        const sessionId="😀".repeat(65)+"tail";
        const body=await payload(model,{cacheRetention:retention,sessionId});
        const expected=Object.fromEntries(Object.entries(body).filter(([key])=>key.startsWith("prompt_cache_")));
        bodyCases.push({name:`cache_${api}_${retention}_explicit_${explicit}`,kind:"cache",model,compat:model.compat,api,retention,session_id:sessionId,api_key:"sk-offline-fixture",expected});
      }
    }
    for(const retention of ["short","long"]){
      const model=baseModel(api,{compat:{supportsLongCacheRetention:false}});
      const body=await payload(model,{cacheRetention:retention,sessionId:"session"});
      bodyCases.push({name:`cache_${api}_${retention}_unsupported`,kind:"cache",model,compat:model.compat,api,retention,session_id:"session",api_key:"sk-offline-fixture",expected:Object.fromEntries(Object.entries(body).filter(([key])=>key.startsWith("prompt_cache_")))});
    }
  }
  for(const retention of ["none","long"]){
    const model=baseModel("openai-responses",{provider:"openai",baseUrl:"https://api.openai.com/v1",compat:{supportsLongCacheRetention:true,supportsExplicitPromptCacheMode:true}});
    const body=await payload(model,{cacheRetention:retention,sessionId:"signin",apiKey:"fake-chatgpt-token"});
    bodyCases.push({name:`cache_chatgpt_${retention}`,kind:"cache",model,compat:model.compat,api:model.api,retention,session_id:"signin",api_key:"fake-chatgpt-token",expected:Object.fromEntries(Object.entries(body).filter(([key])=>key.startsWith("prompt_cache_")))});
  }

  const affinityNames=["session_id","x-session-id","x-client-request-id","x-session-affinity"];
  for(const api of ["openai-completions","openai-responses"]){
    for(const format of ["openai","openrouter","other"]){
      for(const retention of ["short","none"]){
        const compat={sendSessionAffinityHeaders:true,sessionAffinityFormat:format};
        const model=baseModel(api,{compat});
        let headers;
        const fetch=async(_url,init)=>{fakeTransportCalls++;const all=new Headers(init.headers);headers=Object.fromEntries(affinityNames.filter(key=>all.has(key)).map(key=>[key,all.get(key)]));
          const event=api==="openai-completions"?{choices:[{index:0,delta:{content:"ok"},finish_reason:"stop"}]}:{type:"response.completed",response:{id:"resp_fixture",status:"completed",output:[],usage:{input_tokens:0,output_tokens:0,total_tokens:0}}};
          return new Response(`data: ${JSON.stringify(event)}\n\ndata: [DONE]\n\n`,{headers:{"content-type":"text/event-stream"}});};
        const reply=await providers[api].streamSimple(model,{messages},{apiKey:"sk-offline-fixture",fetch,maxRetries:0,sessionId:"session-fixture",cacheRetention:retention}).result();
        if(reply.stopReason==="error") throw new Error(`Header fixture failed: ${reply.errorMessage}`);
        headerCases.push({name:`headers_${api}_${format}_${retention}`,api,compat,session_id:retention==="none"?null:"session-fixture",expected:headers});
      }
    }
  }
  // Completions normally sends no affinity headers except OpenRouter.
  const plainModel=baseModel("openai-completions");
  let plainHeaders;
  const plainFetch=async(_url,init)=>{fakeTransportCalls++;const all=new Headers(init.headers);plainHeaders=Object.fromEntries(affinityNames.filter(key=>all.has(key)).map(key=>[key,all.get(key)]));return new Response('data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',{headers:{"content-type":"text/event-stream"}});};
  await providers[plainModel.api].streamSimple(plainModel,{messages},{apiKey:"sk-offline-fixture",fetch:plainFetch,maxRetries:0,sessionId:"session-fixture"}).result();
  headerCases.push({name:"headers_completions_disabled",api:plainModel.api,compat:{sendSessionAffinityHeaders:false,sessionAffinityFormat:"openai"},session_id:"session-fixture",expected:plainHeaders});

  for(const id of ["gpt-5","gpt-5.5"]){
    for(const tier of ["default","flex","priority","fast",null]){
      const model=baseModel("openai-responses",{id,cost:{input:2,output:8,cacheRead:1,cacheWrite:3}});
      const rawUsage={input_tokens:100,output_tokens:20,total_tokens:120,input_tokens_details:{cached_tokens:30,cache_write_tokens:10}};
      const fetch=async()=>{fakeTransportCalls++;return new Response(`data: ${JSON.stringify({type:"response.completed",response:{id:"resp_cost",status:"completed",output:[],service_tier:tier,usage:rawUsage}})}\n\ndata: [DONE]\n\n`,{headers:{"content-type":"text/event-stream"}});};
      const reply=await providers[model.api].streamSimple(model,{messages},{apiKey:"sk-offline-fixture",fetch,maxRetries:0}).result();
      if(reply.stopReason==="error") throw new Error(`Cost fixture failed: ${reply.errorMessage}`);
      costCases.push({name:`cost_${id}_${tier}`,model_id:id,tier,base_usage:{input:60,output:20,cacheRead:30,cacheWrite:10,totalTokens:120,reasoning:0,cost:{input:0.00012,output:0.00016,cacheRead:0.00003,cacheWrite:0.00003,total:0.00034}},expected:reply.usage});
    }
  }
  const tool={name:"fixture",description:"fixture",parameters:{type:"object",properties:{}}};
  const zero={input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
  const cacheContexts=[
    {name:"string_last_user",messages},
    {name:"last_assistant_empty_skipped",messages:[...messages,{role:"assistant",content:[],usage:zero,stopReason:"stop",api:"openai-completions",provider:"fixture",model:"gpt-5",timestamp:2}]},
    {name:"last_image_only_user_skipped",messages:[...messages,{role:"user",content:[{type:"image",mimeType:"image/png",data:"aGVsbG8="}],timestamp:2}]},
    {name:"last_tool_and_last_tool_definition",messages:[{role:"system",content:"system",toolsAdded:[tool,{...tool,name:"second"}],timestamp:0},messages[1],{role:"assistant",content:[{type:"toolCall",id:"call_one",name:"fixture",arguments:{}}],usage:zero,stopReason:"toolUse",api:"openai-completions",provider:"fixture",model:"gpt-5",timestamp:2},{role:"toolResult",toolCallId:"call_one",toolName:"fixture",content:[{type:"text",text:"first"},{type:"text",text:"last"}],isError:false,timestamp:3}]},
  ];
  for(const context of cacheContexts){
    for(const retention of ["short","long","none"]){
      const model=baseModel("openai-completions",{compat:{cacheControlFormat:"anthropic",supportsLongCacheRetention:true}});
      const expected=await payload(model,{cacheRetention:retention},context.messages);
      // Remove the source annotations to recover the already converted body on
      // which the production helper runs. This isolates cache boundary mutation.
      const before=structuredClone(expected);
      for(const message of before.messages){for(const part of Array.isArray(message.content)?message.content:[]){delete part.cache_control;}}
      for(const item of before.tools??[]){delete item.cache_control;}
      // String conversion belongs to cache placement itself.
      for(let i=0;i<before.messages.length;i++){
        const item=before.messages[i];
        if(Array.isArray(item.content)&&item.content.length===1&&item.content[0].type==="text"&&typeof item.content[0].text==="string"){
          const original=context.messages.find(m=>m.role===item.role&&typeof m.content==="string"&&m.content===item.content[0].text);
          if(original) item.content=item.content[0].text;
        }
      }
      cacheControlCases.push({name:`compat_cache_${context.name}_${retention}`,compat:model.compat,retention,before,expected});
    }
  }
}finally{globalThis.fetch=originalFetch;}
if(networkCalls!==0) throw new Error(`Unexpected network attempts ${networkCalls}`);
const sources=["packages/ai/src/api/openai-completions.ts","packages/ai/src/api/openai-responses.ts","packages/ai/src/api/openai-responses-shared.ts","packages/ai/src/api/openai-prompt-cache.ts","packages/ai/src/api/simple-options.ts"];
const source_sha256=Object.fromEntries(sources.map(name=>[name,createHash("sha256").update(readFileSync(path.join(root,name))).digest("hex")]));
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:"Unmodified original streamSimple; request-body onPayload capture, and fake in-memory fetch/SSE only. No network or model calls.",networkCalls,fakeTransportCalls,source_sha256,bodyCases,headerCases,costCases,cacheControlCases,budgetCases},null,2));
