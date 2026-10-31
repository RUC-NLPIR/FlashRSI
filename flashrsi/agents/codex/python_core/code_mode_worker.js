// V8 cell primitives ported from codex be6e8eac code-mode-runtime/src/runtime.
// Node supplies process transport only. Cell code receives a fresh V8 context;
// no Node object or function is exposed to that context.
"use strict";
const vm = require("node:vm");
const readline = require("node:readline");
const input = readline.createInterface({ input: process.stdin, terminal: false });
let context;
let finished = false;
const timers = new Map();
function send(value) { process.stdout.write(JSON.stringify(value) + "\n"); }
function errorText(error) {
  if (error && typeof error === "object" && typeof error.stack === "string") {
    return error.stack.split("\n").filter(line => !line.trimStart().startsWith("at ") || line.includes("exec_main.mjs")).join("\n");
  }
  return String(error);
}
function finish(error) {
  if (finished) return;
  finished = true;
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  const state = JSON.parse(context.finishState());
  if (state.exit_requested && error === "__codex_code_mode_exit__") error = undefined;
  send({ type: "result", writes: state.writes, error: error === undefined ? null : errorText(error) });
  input.close();
  process.stdin.pause();
}
function bridge(encoded) {
  const event = JSON.parse(encoded);
  if (event.type === "timer") {
    timers.set(event.id, setTimeout(() => {
      timers.delete(event.id);
      if (finished) return;
      try { context.timer(String(event.id)); } catch (error) { finish(error); }
    }, Math.min(event.delay, 2147483647)));
  } else if (event.type === "clear_timer") {
    clearTimeout(timers.get(event.id)); timers.delete(event.id);
  } else send(event);
}
async function start(config) {
  context = vm.createContext(Object.create(null));
  // The temporary host bridge is captured inside context-owned closures, then
  // deleted. All values crossing it are primitive JSON strings.
  context.__transport = bridge;
  const definitions = JSON.stringify(JSON.stringify(config.tools));
  const values = JSON.stringify(JSON.stringify(config.values));
  vm.runInContext(`(function(send, definitions, values) {
    delete globalThis.__transport;
    for (const name of ["console", "Atomics", "SharedArrayBuffer", "WebAssembly"]) delete globalThis[name];
    const emit = event => send(JSON.stringify(event));
    const stored = Object.assign(Object.create(null),JSON.parse(values)), writes = Object.create(null);
    const pending = new Map(), timeouts = new Map();
    let nextTool = 1, nextTimer = 1, exitRequested = false;
    const errorText = error => error && typeof error.stack === "string"
      ? error.stack.split("\\n").filter(line => !line.trimStart().startsWith("at ") || line.includes("exec_main.mjs")).join("\\n")
      : String(error);
    const stringify = value => {
      if (value === null || !["object", "function", "symbol"].includes(typeof value)) return String(value);
      try { const result = JSON.stringify(value); return result === undefined ? String(value) : result; }
      catch (error) { throw errorText(error); }
    };
    const serializable = value => {
      try { return JSON.stringify(value); } catch (error) { throw errorText(error); }
    };
    globalThis.text = function(value) { emit({type:"content", item:{type:"input_text", text:stringify(value)}}); };
    const imageMessage = "image expects a non-empty image URL string, an object with image_url and optional detail, or a raw MCP image block";
    const audioMessage = "audio expects a non-empty audio URL string, an object with audio_url, or a raw MCP audio block";
    function media(value, image, override) {
      let url, detail;
      const helper = image ? "image" : "audio", key = helper + "_url", expected = image ? imageMessage : audioMessage;
      if (typeof value === "string") url = value;
      else if (value && typeof value === "object" && !Array.isArray(value)) {
        if (value[key] !== undefined) {
          if (typeof value[key] !== "string") throw expected;
          url = value[key];
          if (image && value.detail != null && typeof value.detail !== "string") throw "image detail must be a string when provided";
          detail = image ? value.detail : undefined;
        } else {
          const encoded = serializable(value);
          if (encoded === undefined) throw expected;
          value = JSON.parse(encoded);
          if (typeof value.type !== "string") throw expected;
          if (value.type !== helper) throw helper + ' only accepts MCP ' + helper + ' blocks, got "' + value.type + '"';
          if (typeof value.data !== "string" || !value.data) throw helper + " expected MCP " + helper + " data";
          const mime = [value.mimeType,value.mime_type].find(item => typeof item === "string" && item) || "application/octet-stream";
          url = value.data.toLowerCase().startsWith("data:") ? value.data : "data:" + mime + ";base64," + value.data;
          if (image && ["auto","low","high","original"].includes(value._meta?.["codex/imageDetail"])) detail = value._meta["codex/imageDetail"];
        }
      } else throw expected;
      if (!url) throw expected;
      const scheme = url.includes(":") ? url.split(":",1)[0].toLowerCase() : "";
      if (image && ["http","https"].includes(scheme)) throw "Tool call failed: remote image URLs are not supported in tool outputs. Pass a base64 data URI instead";
      if (scheme !== "data") throw "Tool call failed: invalid " + helper + " output. Pass a base64 data URI instead";
      if (image) {
        if (override != null && typeof override !== "string") throw "image detail must be a string when provided";
        detail = override ?? detail ?? "high";
        detail = detail.toLowerCase();
        if (!["auto","low","high","original"].includes(detail)) throw "image detail must be one of: auto, low, high, original";
        return {type:"input_image", image_url:url, detail};
      }
      return {type:"input_audio", audio_url:url};
    }
    globalThis.image = function(value, detail) { emit({type:"content", item:media(value,true,detail)}); };
    globalThis.audio = function(value) { emit({type:"content", item:media(value,false)}); };
    globalThis.generatedImage = function(value) {
      if (value == null || !["object","function"].includes(typeof value)) throw "generatedImage expects an image generation result object";
      const hint = value.output_hint;
      if (hint !== undefined && typeof hint !== "string") throw "generatedImage output_hint must be a string when provided";
      emit({type:"content", item:media(value,true)});
      if (hint !== undefined) text(hint);
    };
    globalThis.store = function(key, value) {
      key = String(key);
      const encoded = serializable(value);
      if (encoded === undefined) throw "Unable to store " + JSON.stringify(key) + ". Only plain serializable objects can be stored.";
      stored[key] = JSON.parse(encoded); writes[key] = JSON.parse(encoded);
    };
    globalThis.load = function(key) { key=String(key); return Object.hasOwn(stored,key) ? JSON.parse(JSON.stringify(stored[key])) : undefined; };
    globalThis.notify = function(value) {
      const text = stringify(value);
      if (!text.trim()) throw "notify expects non-empty text";
      emit({type:"notify", text});
    };
    globalThis.yield_control = function() { emit({type:"yield"}); };
    globalThis.exit = function() { exitRequested=true; throw "__codex_code_mode_exit__"; };
    globalThis.setTimeout = function(callback, delay) {
      if (typeof callback !== "function") throw "setTimeout expects a function callback";
      let value; try { value=Number(delay); } catch (_) { value=0; }
      value = !Number.isFinite(value) || value <= 0 ? 0 : Math.min(Math.trunc(value),18446744073709551615);
      const id = nextTimer++; timeouts.set(id,callback); emit({type:"timer",id,delay:value}); return id;
    };
    globalThis.clearTimeout = function(id) {
      if (id == null) return;
      try { id=Number(id); } catch (_) { throw "clearTimeout expects a numeric timeout id"; }
      if (!Number.isFinite(id) || id <= 0) return;
      id=Math.trunc(id); timeouts.delete(id); emit({type:"clear_timer",id});
    };
    globalThis.tools = {};
    globalThis.ALL_TOOLS = JSON.parse(definitions).map(tool => ({name:tool.global_name,description:tool.description}));
    for (const tool of JSON.parse(definitions)) {
      tools[tool.global_name] = function(input) {
        const encoded = arguments.length ? serializable(input) : undefined;
        const id = "tool-" + nextTool++;
        const promise = new Promise((resolve,reject) => pending.set(id,{resolve,reject}));
        emit({type:"tool",id,name:tool.global_name,has_input:encoded !== undefined,input:encoded === undefined ? null : JSON.parse(encoded)});
        return promise;
      };
    }
    Object.defineProperty(globalThis,"__cellReceive",{value:function(encoded) {
      const response=JSON.parse(encoded), entry=pending.get(response.id); if (!entry) return;
      pending.delete(response.id); response.error === undefined ? entry.resolve(response.value) : entry.reject(response.error);
    },configurable:true});
    Object.defineProperty(globalThis,"__cellTimer",{value:function(id) { id=Number(id); const callback=timeouts.get(id); timeouts.delete(id); if(callback) callback(); },configurable:true});
    Object.defineProperty(globalThis,"__cellFinish",{value:function() { return JSON.stringify({writes,exit_requested:exitRequested}); },configurable:true});
  })(__transport, ${definitions}, ${values});`, context, { filename: "exec_helpers.mjs" });
  // Internal control functions are retained as context functions by the host,
  // then removed from the cell-visible global object before user evaluation.
  const receive = context.__cellReceive, timer = context.__cellTimer, finishState = context.__cellFinish;
  vm.runInContext("delete globalThis.__cellReceive; delete globalThis.__cellTimer; delete globalThis.__cellFinish",context);
  context = { sandbox: context, receive, timer, finishState };
  send({type:"ready"});
  try {
    const module = new vm.SourceTextModule(config.source, {
      context: context.sandbox, identifier: "exec_main.mjs",
      importModuleDynamically: async () => { throw "unsupported import in exec"; },
    });
    await module.link(specifier => { throw "Unsupported import in exec: " + specifier; });
    await module.evaluate();
    finish();
  } catch (error) { finish(error); }
}
input.on("line", line => {
  try {
    const value=JSON.parse(line);
    if(!context) { start(value).catch(error => { send({type:"fatal",error:errorText(error)}); process.exitCode=1; }); }
    else if(!finished) context.receive(JSON.stringify(value));
  } catch(error) { if(context) finish(error); else { send({type:"fatal",error:errorText(error)}); process.exitCode=1; } }
});
process.on("unhandledRejection", () => {});
