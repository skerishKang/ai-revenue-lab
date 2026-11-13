"use strict";
/* Offline Atria explicit single-route SSE aggregation regression. No API key, no network. */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const src = fs.readFileSync(path.join(__dirname,"../static/start.js"),"utf8");
const sandbox = { window: {}, document: { readyState: "complete", getElementById: ()=>null }, console: {error: ()=>{} } };
vm.runInNewContext(src,sandbox,{timeout:3000});
const parse=sandbox.window.Business14Start.readAtriaPreview;
assert.equal(typeof parse,"function");
/* #6828: fixture identities only. The page compares frames against the model
   it asked for, so the fixture model id is a placeholder, never a deployment one. */
const MODEL="padiem/fixture-model";
const meta={route_mode:"manual",selected_model:MODEL,fallback_used:false,attempt_count:1};
const chunk=(content,override={})=>"data: "+JSON.stringify({model:MODEL,business14:meta,choices:[{delta:{content}}],...override})+"\n\n";
const resp=text=>({text:async()=>text});
(async()=>{
 const good=await parse(resp(chunk("견적")+"data: [DONE]\n\n"),MODEL);
 assert.equal(good.error,undefined);
 assert.equal(good.choices[0].message.content,"견적");
 assert.equal(good.business14.selected_model,MODEL);
 const incomplete=await parse(resp(chunk("PARTIAL")),MODEL);
 assert.equal(incomplete.error.code,"stream_incomplete");
 const wrongRoute=await parse(resp(chunk("x",{business14:{...meta,attempt_count:2}})+"data: [DONE]\n\n"),MODEL);
 assert.equal(wrongRoute.error.code,"stream_route_mismatch");
 const wrongModel=await parse(resp(chunk("x",{model:"other-provider"})+"data: [DONE]\n\n"),MODEL);
 assert.equal(wrongModel.error.code,"stream_model_mismatch");
 const streamError=await parse(resp("event: error\ndata: "+JSON.stringify({error:{code:"upstream_timeout",request_id:"synthetic"},business14:meta})+"\n\n"),MODEL);
 assert.equal(streamError.error.code,"upstream_timeout");
 const bad=await parse(resp("data: {broken\n\n"),MODEL);
 assert.equal(bad.error.code,"stream_invalid_frame");
 const huge=await parse(resp("a".repeat(1048577)),MODEL);
 assert.equal(huge.error.code,"stream_too_large");
 const crlf=await parse(resp(chunk("ok").replace(/\n/g,"\r\n")+"data: [DONE]\r\n\r\n"),MODEL);
 assert.equal(crlf.choices[0].message.content,"ok");
 console.log("ATRIA_STREAM_UI_PARSER_TESTS=8 PASS; NETWORK=0");
})().catch(e=>{console.error(e.stack);process.exit(1)});
