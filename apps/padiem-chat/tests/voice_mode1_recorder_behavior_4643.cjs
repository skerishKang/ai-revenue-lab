"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const voice = require("../static/voice-stt-wiring.js");

function setup({empty=false,auto=false}={}) {
  let recorder;
  let time = 1000;
  let level = 0;
  let cancelled = false;
  const posts = [];
  const pending = [];
  const finals = [];
  const turns = [];
  const errors = [];
  const timers = [];
  const tracks = [{stop(){cancelled=true;}}];
  const doc = {querySelector(){return {dataset:{state:"chat"}}}};
  const stream = {getTracks(){return tracks;}};
  class Recorder {
    constructor(){this.state="inactive";recorder=this;}
    static isTypeSupported(){return true;}
    start(){this.state="recording";}
    requestData(){if(this.ondataavailable)this.ondataavailable({data:{size:empty?0:10,type:"audio/webm"}});}
    stop(){this.state="inactive";this.requestData();if(this.onstop)this.onstop();}
  }
  class Blob {constructor(parts,{type}){this.parts=parts;this.type=type;}}
  class Reader {
    readAsDataURL(){this.result="data:audio/webm;base64,AAECAw==";this.onload();}
  }
  global.FileReader = Reader;
  const analyser = {fftSize:1024,getFloatTimeDomainData(buf){buf.fill(level);}};
  const win = {
    PadiemVoiceMode2UI: {isLiveActive:()=>auto},
    MediaRecorder: Recorder, Blob,
    AudioContext: class {
      createMediaStreamSource(){return {connect(){}};}
      createAnalyser(){return analyser;}
      close(){}
    },
    setTimeout(fn){timers.push(fn);return timers.length;},
    clearTimeout(){},
    AbortController: global.AbortController,
  };
  const factory = voice.createRecognizerFactory({
    win, doc,
    fetchImpl: (path,opts)=>{posts.push({path,opts});return new Promise(resolve=>pending.push(resolve));},
    mediaDevices: {getUserMedia:async()=>stream},
    now:()=>time,
  });
  let handle;
  handle = factory({
    onAutoStopRequested:()=>handle.stop("user-stopped"),
    onFinal:p=>finals.push(p),
    onTurnComplete:p=>turns.push(p),
    onError:e=>errors.push(e),
    onEnd:()=>{},
  },{generation:1,sessionToken:"one"});
  const settle=async()=>{for(let i=0;i<14;i++)await Promise.resolve();};
  return {handle,posts,pending,finals,turns,errors,timers,
    recorder:()=>recorder,settle,
    time:t=>time=t,level:x=>level=x,
    resolve(text){const fn=pending.shift();assert.ok(fn);fn({ok:true,json:async()=>({text})});},
    tracksStopped:()=>cancelled};
}

test("user Stop flushes last microphone bytes to editable-final event once", async ()=>{
  const x=setup();await x.settle();assert.ok(x.recorder());
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,1);
  assert.equal(x.posts[0].path,"/api/voice/transcribe");
  x.resolve("마지막 발화");await x.settle();
  assert.equal(x.finals.length,1);
  assert.equal(x.finals[0].text,"마지막 발화");
  assert.equal(x.finals[0].stopped,true);
  assert.equal(x.tracksStopped(),true);
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,1);
});

test("account switch cancel prevents post and late final",async()=>{
  const x=setup();await x.settle();x.handle.stop("account-switch");await x.settle();
  assert.equal(x.posts.length,0);
  assert.equal(x.finals.length,0);
  assert.equal(x.tracksStopped(),true);
});

test("silent empty recorder stop does not bill",async()=>{
  const x=setup({empty:true});await x.settle();x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,0);
});

test("inflight recognition cannot swallow the stop tail",async()=>{
  const x=setup();await x.settle();
  const r=x.recorder();
  r.requestData();
  x.time(5000);x.level(.3);x.timers[0](); // speech started
  x.time(6500);x.level(0);x.timers[0](); // silence after min chunk
  await x.settle();assert.equal(x.posts.length,1);
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,1); // pending final waits for prior POST
  x.resolve("첫 구간");await x.settle();
  assert.equal(x.posts.length,2);
  x.resolve("마지막 구간");await x.settle();
  assert.deepEqual(x.finals.map(v=>v.text),["첫 구간","마지막 구간"]);
  assert.equal(x.finals[0].stopped,true); // the first in-flight final must survive composer.stop()
  assert.equal(x.finals[1].stopped,true);
});

test("Mode2 silence auto-stops once and emits only after accepted provider final", async () => {
  const x=setup({auto:true});await x.settle();
  const r=x.recorder();r.requestData();
  x.time(5000);x.level(.3);x.timers[0]();
  x.time(7701);x.level(0);x.timers[0]();
  await x.settle();
  assert.equal(x.posts.length,1);
  assert.equal(x.turns.length,0); // do not submit an unacknowledged audio chunk
  x.resolve("accepted turn");await x.settle();
  assert.equal(x.finals.length,1);
  assert.equal(x.turns.length,1);
  assert.equal(x.turns[0].accepted,true);
  assert.equal(x.turns[0].endOfTurn,true);
  x.timers[0]();await x.settle();
  assert.equal(x.turns.length,1); // no replay after repeated timer ticks
});

test("inflight Stop plus tail completes only after both provider finals in order",async()=>{
  const x=setup({auto:true});await x.settle();
  const r=x.recorder();r.requestData();
  x.time(5000);x.level(.3);x.timers[0]();
  x.time(6500);x.level(0);x.timers[0]();
  await x.settle();assert.equal(x.posts.length,1);
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.turns.length,0);
  x.resolve("first sentence");await x.settle();
  assert.equal(x.posts.length,2);
  assert.deepEqual(x.finals.map(v=>v.text),["first sentence"]);
  assert.equal(x.turns.length,0);
  x.resolve("second sentence");await x.settle();
  assert.deepEqual(x.finals.map(v=>v.text),["first sentence","second sentence"]);
  assert.equal(x.turns.length,1);
  assert.equal(x.turns[0].finalId,x.finals[1].utteranceId);
});

test("cancel and silent Stop cannot emit accepted end-of-turn",async()=>{
  const cancelled=setup({auto:true});await cancelled.settle();
  cancelled.handle.stop("account-switch");await cancelled.settle();
  assert.equal(cancelled.turns.length,0);
  const silent=setup({auto:true,empty:true});await silent.settle();
  silent.handle.stop("user-stopped");await silent.settle();
  assert.equal(silent.turns.length,0);
});
