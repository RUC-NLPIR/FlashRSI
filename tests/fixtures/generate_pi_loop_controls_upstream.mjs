/** Offline agent-loop control oracle from original Pi v1.4.0 source.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono PI_REFERENCE_DEPS=/path/to/node_modules \
 * node --no-warnings --experimental-loader ./tests/fixtures/pi_compaction_loader.mjs \
 * tests/fixtures/generate_pi_loop_controls_upstream.mjs > tests/fixtures/pi_loop_controls_upstream.json
 * Source control flow is unmodified. Only model replies and tool bodies are fixed.
 */
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {stripTypeScriptTypes} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const root=process.env.PI_REFERENCE_SOURCE;
const commit='4a080252f06caf63a525d7873c5d94d3c23887e0';
if(execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==commit)throw Error('wrong pinned source');
if(JSON.parse(readFileSync(path.join(process.env.PI_REFERENCE_DEPS,'@earendil-works/pi-ai/package.json'))).version!=='1.4.0')throw Error('wrong dependency release');
const {runAgentLoop}=await import(pathToFileURL(path.join(root,'packages/agent/src/agent-loop.ts')).href);
const {createReadTool}=await import(pathToFileURL(path.join(root,'packages/coding-agent/src/core/tools/read.ts')).href);
const {streamSimple}=await import(pathToFileURL(path.join(root,'packages/ai/src/api/openai-completions.ts')).href);
const agentSource=readFileSync(path.join(root,'packages/agent/src/agent.ts'),'utf8');
const queueSource=agentSource.slice(agentSource.indexOf('class PendingMessageQueue {'),agentSource.indexOf('\ntype ActiveRun ='));
const PendingMessageQueue=Function(stripTypeScriptTypes(queueSource)+'; return PendingMessageQueue;')();
const clone=value=>JSON.parse(JSON.stringify(value));
const user=content=>({role:'user',content,timestamp:1});
const text=value=>({type:'text',text:value});
const call=(id='read-1',name='read',args={path:'fixture.txt'})=>({type:'toolCall',id,name,arguments:args});
const reply=(value='done',extra={})=>({content:typeof value==='string'?[text(value)]:value,stopReason:'stop',...extra});
const toolReply=(calls=[call()])=>reply(calls,{stopReason:'toolUse'});
const zero={input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}};
const model={id:'gpt-5',name:'GPT-5',api:'openai-completions',provider:'openai',baseUrl:'https://offline.invalid/v1',reasoning:true,input:['text'],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:128000,maxTokens:4096};
const toolBase={content:[text('executed fixture.txt')],details:{source:'fixture'},structuredContent:{path:'fixture.txt'},usage:{fixture:1},terminate:false};
const inputs=[
 {name:'ordinary_stop',replies:[reply()]},
 ...['one-at-a-time','all'].map(mode=>({name:'steering_'+mode,mode,steering:['steer 1','steer 2'],replies:Array.from({length:mode==='all'?1:2},(_,i)=>reply('answer '+i))})),
 ...['one-at-a-time','all'].map(mode=>({name:'followups_'+mode,mode,followups:['follow 1','follow 2'],replies:Array.from({length:mode==='all'?2:3},(_,i)=>reply('answer '+i))})),
 {name:'continue_context_only',decisions:['continue'],replies:[reply('first'),reply('second')]},
 {name:'continue_satisfied_by_steering',decisions:['continue'],enqueueOnFinish:['steered'],replies:[reply('first'),reply('second')]},
 {name:'continue_satisfied_by_followup',decisions:['continue'],followups:['follow'],replies:[reply('first'),reply('second')]},
 {name:'continue_satisfied_by_tool',decisions:['continue'],tools:['read'],replies:[toolReply(),reply('second')]},
 {name:'end_skips_queued_steering_followup',decisions:['end'],enqueueOnFinish:['keep steering'],followups:['keep followup'],replies:[reply()]},
 {name:'end_skips_tool_continuation',decisions:['end'],tools:['read'],replies:[toolReply()]},
 {name:'prepare_next_messages_before_steering',steering:['initial','already pending'],prepareNext:[{messages:['prepared'],enqueue:['new steering']}],replies:[reply('first'),reply('second'),reply('third')]},
 {name:'prepare_next_repoll_after_compaction',tools:['read'],prepareNext:[{messages:['prepared'],enqueue:['during preparation']}],replies:[toolReply(),reply('second')]},
 {name:'prepare_request_model_thinking_context',prepareRequest:[{model:'gpt-5-mini',thinkingLevel:'high',replace:['request replacement']}],replies:[reply()]},
 {name:'prepare_next_model_thinking_context',thinking:'high',decisions:['continue'],prepareNext:[{model:'gpt-5-mini',thinkingLevel:'off',replace:['next replacement'],messages:['prepared']}],replies:[reply('first'),reply('second')]},
 {name:'transform_context_without_history_mutation',transform:true,decisions:['continue'],replies:[reply('first'),reply('second')]},
 {name:'before_block',tools:['read'],before:{block:true,reason:'policy block'},replies:[toolReply(),reply()]},
 {name:'before_block_default_reason_terminates',tools:['read'],before:{block:true,reason:'',terminate:true},replies:[toolReply()]},
 {name:'before_throw_skips_after',tools:['read'],beforeThrow:'before failed',replies:[toolReply(),reply()]},
 {name:'after_overrides_content_drops_structured',tools:['read'],after:{content:[text('replacement')],details:{overridden:true},usage:{fixture:2},isError:true,terminate:true},replies:[toolReply()]},
 {name:'after_overrides_structured',tools:['read'],after:{content:[],structuredContent:{replacement:true},details:null,usage:null,terminate:true,isError:false},replies:[toolReply()]},
 {name:'after_null_preserves_fields',tools:['read'],after:{content:null,structuredContent:null,details:null,usage:null,isError:null,terminate:true},replies:[toolReply()]},
 {name:'after_throw_replaces_executed_result',tools:['read'],afterThrow:'after failed',replies:[toolReply(),reply()]},
 {name:'all_results_must_terminate',tools:['read'],afterById:{'read-1':{terminate:true},'read-2':{terminate:false}},replies:[toolReply([call(),call('read-2')]),reply()]},
 {name:'all_results_terminate',tools:['read'],after:{terminate:true},replies:[toolReply([call(),call('read-2')])]},
 {name:'unknown_tool_skips_hooks',tools:['read'],replies:[toolReply([call('missing','unknown')]),reply()]},
 {name:'error_is_hard_exit_despite_continue',decisions:['continue'],enqueueOnFinish:['keep steering'],followups:['keep followup'],replies:[reply('partial',{stopReason:'error',errorMessage:'fixture error'})]},
 {name:'aborted_is_hard_exit_despite_continue',decisions:['continue'],enqueueOnFinish:['keep steering'],followups:['keep followup'],replies:[reply('partial',{stopReason:'aborted',errorMessage:'Request aborted'})]},
];
const chunk=(delta={},finish=null,extra={})=>({id:'chat_fixture',model:'gpt-5',choices:[{index:0,delta,finish_reason:finish}],...extra});
inputs.push({name:'stream_text_thinking_mapping',wire:[chunk({reasoning_content:'thought'}),chunk({content:'hel'}),chunk({content:'lo'}),chunk({},'stop',{usage:{prompt_tokens:0,completion_tokens:0}})]});
inputs.push({name:'stream_tool_mapping',tools:['read'],after:{terminate:true},wire:[chunk({tool_calls:[{index:0,id:'read-1',function:{name:'read',arguments:'{"path":'}}]}),chunk({tool_calls:[{index:0,function:{arguments:'"fixture.txt"}'}}]}),chunk({},'tool_calls',{usage:{prompt_tokens:0,completion_tokens:0}})]});
function messageSummary(message){
 const result={role:message.role,content:message.content??[]};
 if(message.role==='assistant'){result.stopReason=message.stopReason;if(message.thinkingLevel!==undefined)result.thinkingLevel=message.thinkingLevel;}
 if(message.role==='toolResult')for(const key of ['toolCallId','toolName','isError','details','usage'])if(message[key]!==undefined)result[key]=message[key];
 return clone(result);
}
const messagesSummary=messages=>messages.filter(message=>message.role!=='system').map(messageSummary);
function normalize(value){
 if(Array.isArray(value))return value.map(normalize);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>!['timestamp','durationMs'].includes(key)).map(([key,item])=>[key,normalize(item)]));
 return value;
}
function eventSummary(event,stream){
 const result={type:event.type};
 if(['agent_settled','session'].includes(event.type)||event.message?.role==='system'||(!stream&&event.type==='message_update'))return null;
 if(event.message){
  result.message=messageSummary(event.message);
  // Fixed fake streams do not exercise provider partial-message metadata.
  // Actual SSE cases below retain and compare it without this normalization.
  if(!stream&&event.type==='message_start'&&event.message.role==='assistant'){
   delete result.message.stopReason;delete result.message.thinkingLevel;
  }
 }
 if(event.messages)result.messages=messagesSummary(event.messages);
 if(event.toolResults)result.toolResults=event.toolResults.map(messageSummary);
 for(const key of ['toolCallId','toolName','args','result','isError','partialResult'])if(event[key]!==undefined)result[key]=normalize(event[key]);
 if(stream&&event.assistantMessageEvent)result.assistantMessageEvent=normalize(event.assistantMessageEvent);
 return result;
}
let networkCalls=0,fakeFetchCalls=0;
const originalFetch=globalThis.fetch;
globalThis.fetch=async()=>{networkCalls++;throw Error('forbidden network')};
const cases=[];
try{for(const input of inputs){
 const steering=new PendingMessageQueue(input.mode??'one-at-a-time'),followup=new PendingMessageQueue(input.mode??'one-at-a-time');
 for(const value of input.steering??[])steering.enqueue(user(value));
 for(const value of input.followups??[])followup.enqueue(user(value));
 const timeline=[],requests=[],events=[];
 let requestIndex=0,turn=0,prepareIndex=0;
 const record=(hook,value={})=>timeline.push({hook,...clone(value)});
 const tools=input.tools?.length?[{...createReadTool(root),async execute(id,args){record('execute',{id,args});return clone(toolBase);}}]:[];
 const context={messages:[{role:'system',content:'fixture system',timestamp:0,...(tools.length?{toolsAdded:tools.map(({name,description,parameters})=>({name,description,parameters}))}:{})}],tools};
 const update=spec=>{
  if(!spec)return undefined;
  for(const value of spec.enqueue??[])steering.enqueue(user(value));
  return {...(spec.replace?{context:{messages:spec.replace.map(user),tools}}:{}),...(spec.messages?{messages:spec.messages.map(user)}:{}),...(spec.model?{model:{...model,id:spec.model}}:{}),...(spec.thinkingLevel!==undefined?{thinkingLevel:spec.thinkingLevel}:{})};
 };
 const config={model,reasoning:input.thinking,apiKey:'sk-offline-fixture',toolExecution:'sequential',
  getSteeringMessages:async()=>{const messages=steering.drain();record('getSteeringMessages',{messages:messagesSummary(messages)});return messages;},
  getFollowUpMessages:async()=>{const messages=followup.drain();record('getFollowUpMessages',{messages:messagesSummary(messages)});return messages;},
  prepareRequest:async request=>{record('prepareRequest',{messages:messagesSummary(request.context.messages),model:request.model.id,thinkingLevel:request.thinkingLevel});return update(input.prepareRequest?.[requestIndex]);},
  prepareNextTurn:async completed=>{record('prepareNextTurn',{message:messageSummary(completed.message),toolResults:completed.toolResults.map(messageSummary),messages:messagesSummary(completed.context.messages),newMessages:messagesSummary(completed.newMessages)});return update(input.prepareNext?.[prepareIndex++]);},
  transformContext:async messages=>{record('transformContext',{messages:messagesSummary(messages)});return input.transform?[...messages,user('transformed request')]:messages;},
  convertToLlm:async messages=>{record('convertToLlm',{messages:messagesSummary(messages)});return messages;},
  getApiKey:async provider=>{record('getApiKey',{provider});return 'sk-hook-fixture';},
  finishTurn:async completed=>{record('finishTurn',{message:messageSummary(completed.message),toolResults:completed.toolResults.map(messageSummary),messages:messagesSummary(completed.context.messages),newMessages:messagesSummary(completed.newMessages)});if(turn===0)for(const value of input.enqueueOnFinish??[])steering.enqueue(user(value));const action=input.decisions?.[turn++];return action?{action}:undefined;},
  beforeToolCall:async ctx=>{record('beforeToolCall',{toolCall:ctx.toolCall,args:ctx.args,messages:messagesSummary(ctx.context.messages)});if(input.beforeThrow)throw Error(input.beforeThrow);return input.before;},
  afterToolCall:async ctx=>{record('afterToolCall',{toolCall:ctx.toolCall,args:ctx.args,result:ctx.result,isError:ctx.isError,messages:messagesSummary(ctx.context.messages)});if(input.afterThrow)throw Error(input.afterThrow);return input.afterById?.[ctx.toolCall.id]??input.after;},
 };
 const streamFn=async(actualModel,llmContext,options)=>{
  requests.push({model:actualModel.id,thinkingLevel:options.reasoning??'off',apiKey:options.apiKey,messages:messagesSummary(llmContext.messages)});
  record('request',{index:requestIndex});
  if(input.wire){
   requestIndex++;
   const fetch=async()=>{fakeFetchCalls++;return new Response(input.wire.map(value=>'data: '+JSON.stringify(value)+'\n\n').join('')+'data: [DONE]\n\n',{headers:{'content-type':'text/event-stream'}});};
   return streamSimple(actualModel,llmContext,{...options,fetch,maxRetries:0});
  }
  const fixed=input.replies[requestIndex++];if(!fixed)throw Error('Unexpected extra request '+input.name);
  const final={role:'assistant',api:actualModel.api,provider:actualModel.provider,model:actualModel.id,usage:clone(zero),timestamp:2,...clone(fixed)};
  return {async result(){return final;},async *[Symbol.asyncIterator](){yield {type:'start',partial:{...final,content:[],stopReason:'stop'}};yield {type:final.stopReason==='error'||final.stopReason==='aborted'?'error':'done',[final.stopReason==='error'||final.stopReason==='aborted'?'error':'message']:final};}};
 };
 const newMessages=await runAgentLoop([user('fixture task')],context,config,async event=>{const value=eventSummary(clone(event),!!input.wire);if(value){events.push(value);timeline.push({event:value});}},undefined,streamFn);
 cases.push({input,expected:{timeline,events,requests,messages:messagesSummary(newMessages),remainingSteering:messagesSummary(steering.messages),remainingFollowups:messagesSummary(followup.messages)}});
}}finally{globalThis.fetch=originalFetch;}
if(networkCalls)throw Error('network attempted');
const queueCases=[];
for(const mode of ['one-at-a-time','all']){
 const queue=new PendingMessageQueue(mode),steps=[];
 for(const action of [['hasItems'],['peek'],['enqueue',user('a')],['enqueue',user('b')],['peek'],['hasItems'],['drain'],['peek'],['enqueue',user('c')],['drain'],['hasItems'],['clear'],['peek']]){
  const value=queue[action[0]](...action.slice(1));steps.push({action,value:value===undefined?null:value,messages:clone(queue.messages)});
 }
 queueCases.push({mode,steps});
}
const sources=['packages/agent/src/agent-loop.ts','packages/agent/src/agent.ts','packages/agent/src/types.ts','packages/ai/src/api/openai-completions.ts','packages/coding-agent/src/core/tools/read.ts'];
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:'Actual original runAgentLoop and extracted unmodified PendingMessageQueue. Fixed model replies and tool bodies; streaming cases run original OpenAI streamSimple on fake SSE. System-resource declarations and provider metadata are excluded from semantic summaries. Nonstream fake-start stopReason/thinkingLevel are excluded. Streaming assistantMessageEvent snapshots retain all fields except clocks, captured at the source loop observer boundary. No network/model calls.',networkCalls,fakeFetchCalls,source_sha256:Object.fromEntries(sources.map(name=>[name,createHash('sha256').update(readFileSync(path.join(root,name))).digest('hex')])),toolBase,cases,queueCases},null,2));
