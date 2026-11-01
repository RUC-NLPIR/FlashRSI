/** Actual original Pi provider SSE processors, captured at stream.push.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs
 * tests/fixtures/generate_pi_openai_stream_upstream.mjs > tests/fixtures/pi_openai_stream_upstream.json
 * Fake in-memory fetch only; no account, network, or model generation.
 */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const root=process.env.PI_REFERENCE_SOURCE,deps=process.env.PI_REFERENCE_DEPS;
const commit='4a080252f06caf63a525d7873c5d94d3c23887e0';
if(execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==commit)throw Error('wrong pinned source');
const pkg=path.join(deps,'@earendil-works/pi-ai');
if(JSON.parse(readFileSync(path.join(pkg,'package.json'))).version!=='1.4.0')throw Error('wrong release');
const {MODELS}=await import(pathToFileURL(path.join(pkg,'dist/models.generated.js')).href);
const providers={};
for(const api of ['openai-completions','openai-responses'])providers[api]=await import(pathToFileURL(path.join(root,`packages/ai/src/api/${api}.ts`)).href);
const grammar={name:'code',description:'code',parameters:{type:'object',properties:{program:{type:'string'}},required:['program']},constrainedSampling:{type:'grammar',variants:{openai_lark:'start: /[\\s\\S]*/'}}};
const context=[{role:'system',content:'fixture',toolsAdded:[{name:'read',description:'read',parameters:{type:'object',properties:{path:{type:'string'}},required:['path']}},grammar],timestamp:0},{role:'user',content:'hello',timestamp:1}];
const usage={prompt_tokens:100,completion_tokens:20,prompt_tokens_details:{cached_tokens:30,cache_write_tokens:10},completion_tokens_details:{reasoning_tokens:4}};
const rusage={input_tokens:100,output_tokens:20,total_tokens:120,input_tokens_details:{cached_tokens:30,cache_write_tokens:10},output_tokens_details:{reasoning_tokens:4}};
const chunk=(delta={},finish=null,extra={})=>({id:'chat_fixture',model:'gpt-5',choices:[{index:0,delta,finish_reason:finish}],...extra});
const done=(reason='stop',extra={})=>chunk({},reason,{usage,...extra});
const created={type:'response.created',response:{id:'resp_fixture'}};
const added=(index,item)=>({type:'response.output_item.added',output_index:index,item});
const itemDone=(index,item)=>({type:'response.output_item.done',output_index:index,item});
const terminal=(status='completed',extra={})=>({type:status==='incomplete'?'response.incomplete':'response.completed',response:{id:'resp_fixture',status,usage:rusage,output:[],...extra}});
const textItem=(id,text,extra={})=>({type:'message',id,role:'assistant',content:[{type:'output_text',text,annotations:[]}],...extra});
const call=(extra={})=>({type:'function_call',id:'fc_fixture',call_id:'call_fixture',name:'read',arguments:'',...extra});
const inputs=[];
const chat=(name,wire,extra={})=>inputs.push({name,api:'openai-completions',wire,...extra});
const responses=(name,wire,extra={})=>inputs.push({name,api:'openai-responses',wire:[created,...wire],...extra});
chat('chat_text',[chunk({content:'hel'}),chunk({content:'lo'}),done()]);
chat('chat_thinking_before_text_and_interleaved',[chunk({reasoning_content:'first',reasoning:'duplicate',content:'answer'}),chunk({reasoning_text:'later'}),done()]);
chat('chat_reasoning_details_merge',[chunk({reasoning_details:[{type:'reasoning.text',text:'one',id:'d1'},{type:'reasoning.text',text:'two',signature:'sig',format:'openrouter-v1'},{type:'reasoning.summary',summary:'sum'},{type:'reasoning.summary',summary:'mary',index:2},{type:'reasoning.encrypted',data:'opaque',id:'encrypted'},{type:'invalid',text:'ignored'}]}),chunk({content:'done'}),done()]);
chat('chat_reasoning_details_validation_and_null_merge',[chunk({reasoning_details:[{type:'reasoning.text',text:'bad',signature:7},{type:'reasoning.text',text:'bad',format:null},{type:'reasoning.summary',summary:'bad',index:true},{type:'reasoning.text',text:'first',id:null,signature:null,format:''},{type:'reasoning.text',text:'second'},{type:'reasoning.summary',summary:'one',signature:'metadata'},{type:'reasoning.summary',summary:'two',signature:'other'}]}),done()]);
chat('chat_opencode_reasoning_signature',[chunk({reasoning:'thought'}),done()],{provider:'opencode-go'});
chat('chat_interleaved_tools',[chunk({tool_calls:[{index:0,id:'a',function:{name:'read',arguments:'{"path":"'}},{index:1,id:'b',function:{name:'read',arguments:'{"path":"b'}}]}),chunk({tool_calls:[{index:1,function:{arguments:'.txt"}'}},{index:0,function:{arguments:'a.txt"}'}}]}),done('tool_calls')]);
chat('chat_late_id_name',[chunk({tool_calls:[{index:0,function:{arguments:'{"path":'}}]}),chunk({tool_calls:[{index:0,id:'late',function:{name:'read',arguments:'"a"}'}}]}),done('tool_calls')]);
chat('chat_id_only_correlates',[chunk({tool_calls:[{id:'a',function:{name:'read',arguments:'{"path":'}}]}),chunk({tool_calls:[{id:'a',function:{arguments:'"a"}'}}]}),done('tool_calls')]);
chat('chat_custom_grammar_fragments',[chunk({tool_calls:[{index:0,id:'ctc',custom:{name:'code',input:'print("'}}]}),chunk({tool_calls:[{index:0,custom:{input:'😊")\n'}}]}),done('tool_calls')]);
chat('chat_unknown_custom_empty',[chunk({tool_calls:[{index:0,id:'ctc',custom:{name:'unknown',input:''}}]}),done('tool_calls')]);
chat('chat_custom_empty_object',[chunk({tool_calls:[{index:0,id:'ctc',custom:{}}]}),done('tool_calls')]);
chat('chat_usage_nullish_cache_fallback',[done('stop',{usage:{prompt_tokens:100,completion_tokens:2,prompt_cache_hit_tokens:30,prompt_tokens_details:{cached_tokens:null,cache_write_tokens:10}}})]);
for(const raw of ['{"path":"a','[1,2]','{"path":"c:\\docs"}','{"path":','{"path":true,}'])chat('chat_arguments_'+raw,[chunk({tool_calls:[{index:0,id:'a',function:{name:'read',arguments:raw}}]}),done('tool_calls')]);
chat('chat_partial_argument_prefixes',['{','"path"',':','"a','\\','n','b"',',"nested":[1,','2',']}'].map((argumentsPart,index)=>chunk({tool_calls:[{index:0,...(index===0?{id:'a'}:{}),function:{...(index===0?{name:'read'}:{}),arguments:argumentsPart}}]})).concat(done('tool_calls')));
chat('chat_no_finish',[chunk({content:'partial'})]);
chat('chat_no_finish_supported_false',[chunk({content:'accepted'})],{compat:{supportsFinishReason:false}});
chat('chat_empty',[]);
chat('chat_usage_only',[{id:'chat_fixture',choices:[],usage}]);
chat('chat_response_model_and_choice_usage',[chunk({content:'routed'},'stop',{model:'routed-model',usage:null,choices:[{index:0,delta:{content:'routed'},finish_reason:'stop',usage:{...usage,prompt_tokens:10,prompt_tokens_details:{cached_tokens:30,cache_write_tokens:10}}}]})]);
for(const reason of ['content_filter','network_error','other','length'])chat('chat_finish_'+reason,[chunk({content:'partial'}),done(reason)]);
chat('chat_raw_error',[chunk({content:'partial'}),{error:{message:'offline stream error',type:'server_error',code:'fixture'}}]);
for(const delta of [{content:'partial'},{reasoning_content:'thought'},{tool_calls:[{index:0,id:'partial',function:{name:'read',arguments:'{"path":"a'}}]},{reasoning_details:[{type:'reasoning.encrypted',data:'opaque',id:'e'}]},{tool_calls:[{index:0,id:'partial',custom:{name:'code',input:'partial'}}]}])chat('chat_abort_'+Object.keys(delta)[0], [chunk(delta)],{abort:true});
chat('chat_transport_fail',[chunk({content:'partial'})],{fail:'offline transport failure'});

responses('responses_text_slots',[added(1,textItem('msg_b','')),added(0,textItem('msg_a','')),{type:'response.output_text.delta',output_index:0,delta:'first'},{type:'response.output_text.delta',output_index:1,delta:'second'},itemDone(0,textItem('msg_a','First',{phase:'commentary'})),itemDone(1,textItem('msg_b','Second',{phase:'final_answer'})),terminal()]);
const reasoning={type:'reasoning',id:'rs_fixture',summary:[{type:'summary_text',text:'One'},{type:'summary_text',text:'Two'}]};
responses('responses_reasoning_encrypted_backfill',[added(0,{type:'reasoning',id:'rs_fixture',summary:[]}),{type:'response.reasoning_summary_text.delta',output_index:0,delta:'One'},{type:'response.reasoning_summary_part.done',output_index:0},{type:'response.reasoning_summary_text.delta',output_index:0,delta:'Two'},itemDone(0,reasoning),terminal('completed',{output:[{...reasoning,encrypted_content:'opaque'}]})]);
responses('responses_reasoning_content',[added(0,{type:'reasoning',id:'rs_fixture',summary:[]}),{type:'response.reasoning_text.delta',output_index:0,delta:'raw'},itemDone(0,{type:'reasoning',id:'rs_fixture',summary:[],content:[{type:'reasoning_text',text:'authoritative'}],encrypted_content:'sig'}),terminal()]);
responses('responses_function_argument_done_suffix',[added(0,call()),{type:'response.function_call_arguments.delta',output_index:0,delta:'{"path":'},{type:'response.function_call_arguments.done',output_index:0,arguments:'{"path":"a"}'},itemDone(0,call({arguments:'{"path":"a"}',namespace:'fixture'})),terminal()]);
responses('responses_function_done_replaces_arguments',[added(0,call({arguments:'{"path":'})),{type:'response.function_call_arguments.delta',output_index:0,delta:'"a"}'},{type:'response.function_call_arguments.done',output_index:0,arguments:'{"path":"b"}'},itemDone(0,call({arguments:'{"path":"b"}'})),terminal()]);
responses('responses_function_done_only',[itemDone(0,call({arguments:'{"path":"a"}'})),terminal()]);
const custom={type:'custom_tool_call',id:'ctc_fixture',call_id:'call_fixture',name:'code',input:''};
responses('responses_custom_fragments',[added(0,custom),{type:'response.custom_tool_call_input.delta',output_index:0,delta:'line1\n'},{type:'response.custom_tool_call_input.done',output_index:0,input:'line1\n😊"\\'},itemDone(0,{...custom,input:'line1\n😊"\\',namespace:'fixture'}),terminal()]);
responses('responses_unknown_custom_done_only',[itemDone(0,{...custom,name:'unknown',input:'raw'}),terminal()]);
responses('responses_custom_nonmonotonic_error',[added(0,custom),{type:'response.custom_tool_call_input.delta',output_index:0,delta:'abc'},{type:'response.custom_tool_call_input.done',output_index:0,input:'xyz'},terminal()]);
responses('responses_text_refusal',[added(0,textItem('msg_fixture','')),{type:'response.refusal.delta',output_index:0,delta:'Refuse. '},{type:'response.output_text.delta',output_index:0,delta:'Alternative.'},itemDone(0,{...textItem('msg_fixture',''),content:[{type:'refusal',refusal:'Refuse. '},{type:'output_text',text:'Alternative.'}]}),terminal()]);
responses('responses_unfinished_tool',[added(0,call()),{type:'response.function_call_arguments.delta',output_index:0,delta:'{"path":"a'},terminal()]);
responses('responses_partial_tool_length',[added(0,call()),{type:'response.function_call_arguments.delta',output_index:0,delta:'{"path":"a'},terminal('incomplete',{incomplete_details:{reason:'max_output_tokens'}})]);
responses('responses_no_terminal',[added(0,textItem('msg_fixture','')),{type:'response.output_text.delta',output_index:0,delta:'partial'}]);
responses('responses_missing_added_ignored_delta',[{type:'response.output_text.delta',output_index:3,delta:'ignored'},itemDone(3,textItem('msg_final','done')),terminal()]);
responses('responses_phase_effort',[itemDone(0,textItem('msg_fixture','done',{phase:'final_answer'})),terminal()],{compat:{supportsMidConvoEffort:true},reasoning:'high',managed_effort:'high'});
for(const reason of ['max_output_tokens','content_filter',null])responses('responses_incomplete_'+reason,[terminal('incomplete',{...(reason?{incomplete_details:{reason}}:{})})]);
for(const status of ['cancelled','fixture_unknown'])responses('responses_status_'+status,[terminal(status)]);
responses('responses_failed',[{type:'response.failed',response:{status:'failed',error:{code:'server_error',message:'offline failure'}}}]);
responses('responses_event_error',[{type:'error',code:'fixture',message:'offline event error'}]);
responses('responses_service_tier',[terminal('completed',{service_tier:'priority'})]);
for(const raw of ['{"path":"a','[1,2]','{"path":true,}'])responses('responses_arguments_'+raw,[itemDone(0,call({arguments:raw})),terminal()]);
responses('responses_abort_text',[added(0,textItem('msg_fixture','')),{type:'response.output_text.delta',output_index:0,delta:'partial'}],{abort:true});
responses('responses_abort_tool',[added(0,call()),{type:'response.function_call_arguments.delta',output_index:0,delta:'{"path":"a'}],{abort:true});
responses('responses_transport_fail',[added(0,textItem('msg_fixture','')),{type:'response.output_text.delta',output_index:0,delta:'partial'}],{fail:'offline transport failure'});

const normalize=value=>{
  if(Array.isArray(value))return value.map(normalize);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>!['timestamp','durationMs'].includes(key)).map(([key,item])=>[key,normalize(item)]));
  return value;
};
let networkCalls=0,fakeFetchCalls=0;
const originalFetch=globalThis.fetch;
globalThis.fetch=async()=>{networkCalls++;throw Error('forbidden network')};
const cases=[];
try{
  for(const input of inputs){
    const model={...structuredClone(MODELS.openai['gpt-5']),api:input.api,provider:input.provider??'openai',baseUrl:'https://offline.invalid/v1',compat:{supportsOpenAIGrammarTools:true,supportsMidConvoEffort:false,...input.compat}};
    const controller=new AbortController();
    const encoded=input.wire.map(event=>new TextEncoder().encode((input.api==='openai-responses'?`event: ${event.type==='error'?'response.fixture':event.type}\n`:'')+`data: ${JSON.stringify(event)}\n\n`));
    let index=0;
    const fetch=async()=>{fakeFetchCalls++;return new Response(new ReadableStream({async pull(stream){
      if(index<encoded.length){stream.enqueue(encoded[index++]);return;}
      await new Promise(setImmediate);
      if(input.abort){controller.abort();stream.error(new Error('Request aborted'));}
      else if(input.fail)stream.error(new Error(input.fail));
      else stream.close();
    }}),{headers:{'content-type':'text/event-stream'}})};
    const stream=providers[input.api].streamSimple(model,{messages:structuredClone(context)},{apiKey:'sk-offline-fixture',fetch,maxRetries:0,signal:controller.signal,reasoning:input.reasoning});
    const events=[];
    const originalPush=stream.push.bind(stream);
    stream.push=event=>{events.push(normalize(JSON.parse(JSON.stringify(event))));return originalPush(event)};
    const reply=await stream.result();
    const config={llm:{model_name:`${model.provider}/${model.id}`,model_api:input.api,base_url:model.baseUrl,api_key:'sk-offline-fixture'}};
    cases.push({input:{...input,config,model,context:structuredClone(context)},expected:{events,message:normalize(reply)}});
  }
}finally{globalThis.fetch=originalFetch;}
if(networkCalls)throw Error('network attempted');
const sources=['packages/ai/src/api/openai-completions.ts','packages/ai/src/api/openai-responses.ts','packages/ai/src/api/openai-responses-shared.ts','packages/ai/src/api/constrained-sampling.ts','packages/ai/src/utils/json-parse.ts','packages/ai/src/utils/event-stream.ts'];
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:'Actual original streamSimple and SDK consume fake in-memory SSE; stream.push snapshots cloned synchronously. Only timestamp/durationMs clock fields normalized. No network or model calls.',networkCalls,fakeFetchCalls,source_sha256:Object.fromEntries(sources.map(name=>[name,createHash('sha256').update(readFileSync(path.join(root,name))).digest('hex')])),cases},null,2));
