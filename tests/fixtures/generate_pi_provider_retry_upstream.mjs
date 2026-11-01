/** Offline oracle: execute the pinned original provider-retry.ts, no network.
 * PI_REFERENCE_SOURCE=/path/to/pi-mono node --no-warnings \
 *   tests/fixtures/generate_pi_provider_retry_upstream.mjs > tests/fixtures/pi_provider_retry_upstream.json
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";

const root = process.env.PI_REFERENCE_SOURCE;
const commit = "4a080252f06caf63a525d7873c5d94d3c23887e0";
if (execFileSync("git", ["-C", root, "rev-parse", "HEAD"], {encoding:"utf8"}).trim() !== commit) throw new Error("Wrong Pi source revision");
const source = "packages/ai/src/utils/provider-retry.ts";
const {retryProviderRequest} = await import(pathToFileURL(path.join(root, source)).href);
const fixedNow = 1735689600000;
const fixedRandom = 0.4;
const cases = [
  ...[400,408,409,429,499,500,599].map(status => ({name:`status_${status}`,status,retries:1})),
  {name:"default_no_retries",status:500},
  {name:"explicit_header_retry_400",status:400,retries:1,headers:{"x-should-retry":"true"}},
  {name:"explicit_header_no_retry_500",status:500,retries:3,headers:{"x-should-retry":"false"}},
  {name:"case_sensitive_header_value",status:400,retries:1,headers:{"x-should-retry":"TRUE"}},
  {name:"retry_after_ms_priority",status:429,retries:1,headers:{"retry-after-ms":"125","retry-after":"5"}},
  {name:"retry_after_ms_zero",status:429,retries:1,headers:{"retry-after-ms":"0","retry-after":"5"}},
  {name:"retry_after_ms_numeric_prefix",status:429,retries:1,headers:{"retry-after-ms":"125ms"}},
  {name:"retry_after_ms_invalid_falls_back",status:429,retries:1,headers:{"retry-after-ms":"bad","retry-after":"1.25"}},
  {name:"retry_after_ms_infinite_falls_back",status:429,retries:1,headers:{"retry-after-ms":"Infinity","retry-after":"2"}},
  {name:"retry_after_seconds_prefix",status:429,retries:1,headers:{"retry-after":"1.5 seconds"}},
  {name:"retry_after_http_date",status:429,retries:1,headers:{"retry-after":"Wed, 01 Jan 2025 00:00:04 GMT"}},
  {name:"retry_after_past_date",status:429,retries:1,headers:{"retry-after":"Tue, 31 Dec 2024 23:59:59 GMT"}},
  {name:"negative_server_delay",status:429,retries:1,headers:{"retry-after-ms":"-3"}},
  {name:"bad_headers_use_jitter",status:429,retries:1,headers:{"retry-after-ms":"bad","retry-after":"bad"}},
  {name:"server_delay_exceeds_default",status:429,retries:1,headers:{"retry-after":"61"}},
  {name:"server_delay_exceeds_custom",status:429,retries:1,maxRetryDelayMs:1000,headers:{"retry-after-ms":"1001"}},
  {name:"server_delay_limit_disabled",status:429,retries:1,maxRetryDelayMs:0,headers:{"retry-after":"300"}},
  {name:"exponential_limit_and_jitter",status:500,retries:7,failures:7},
  {name:"server_max_does_not_cap_backoff",status:500,retries:3,failures:3,maxRetryDelayMs:100},
  {name:"network_provider_error",retries:1,network:true},
  {name:"non_provider_error_no_retry",retries:1,nonProvider:true},
  {name:"retry_budget_exhausted",status:500,retries:2,failures:3},
  {name:"excluded_retryable_status",status:504,retries:2,noRetryStatuses:[504],headers:{"retry-after-ms":"0"}},
  {name:"excluded_status_overrides_retry_header",status:400,retries:2,noRetryStatuses:[400],headers:{"x-should-retry":"true"}},
  {name:"no_retry_budget_ignores_long_delay",status:429,headers:{"retry-after":"99999"}},
];
const originalTimer = globalThis.setTimeout;
const originalClear = globalThis.clearTimeout;
const originalNow = Date.now;
const originalRandom = Math.random;
try {
  Date.now = () => fixedNow;
  Math.random = () => fixedRandom;
  for (const input of cases) {
    let calls=0;
    const delaysMs=[];
    globalThis.setTimeout=(fn,ms)=>{delaysMs.push(ms);queueMicrotask(fn);return 1;};
    globalThis.clearTimeout=()=>{};
    const request=async()=>{
      calls++;
      if(calls>(input.failures??1)) return {ok:true};
      const error=new Error(input.status===undefined?"fixture failure":`${input.status}: fixture failure`);
      if(!input.nonProvider){
        error.status=input.status;
        error.headers=input.network?undefined:new Headers(input.headers??{});
      }
      throw error;
    };
    let expected;
    try {
      const output=await retryProviderRequest(request,{
        ...(input.retries===undefined?{}:{maxRetries:input.retries}),
        ...(input.maxRetryDelayMs===undefined?{}:{maxRetryDelayMs:input.maxRetryDelayMs}),
        ...(input.noRetryStatuses===undefined?{}:{noRetryStatuses:input.noRetryStatuses}),
      });
      expected={calls,delaysMs,output};
    } catch(error) { expected={calls,delaysMs,error:error.message}; }
    input.expected=expected;
  }
} finally {
  globalThis.setTimeout=originalTimer;
  globalThis.clearTimeout=originalClear;
  Date.now=originalNow;
  Math.random=originalRandom;
}
console.log(JSON.stringify({baseline:`v1.4.0@${commit}`,method:"Unmodified original retryProviderRequest with fixed time/random and immediate recorded timers; offline, no model requests.",source_sha256:{[source]:createHash("sha256").update(readFileSync(path.join(root,source))).digest("hex")},fixedNow,fixedRandom,cases},null,2));
