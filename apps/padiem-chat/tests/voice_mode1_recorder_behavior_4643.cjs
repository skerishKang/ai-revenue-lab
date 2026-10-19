"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const voice = require("../static/voice-stt-wiring.js");

function setup({empty=false}={}) {
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
  const handle = factory({
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
    fail(){const fn=pending.shift();assert.ok(fn);fn({ok:false,json:async()=>({error:{code:"transcribe_failed"}})});},
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

// #4698: the wiring reports an accepted turn only after its transcript exists.
// The composer gates which of these it forwards; an accepted turn without a
// matching finalId would auto-send an unacknowledged or empty utterance.
test("accepted turn is emitted only after the provider final arrives",async()=>{
  const x=setup();await x.settle();
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,1);
  assert.equal(x.turns.length,0); // nothing is accepted while the POST is pending
  x.resolve("확정 발화");await x.settle();
  assert.equal(x.finals.length,1);
  assert.equal(x.turns.length,1);
  assert.equal(x.turns[0].accepted,true);
  assert.equal(x.turns[0].endOfTurn,true);
  assert.equal(x.turns[0].finalId,x.finals[0].utteranceId); // the final it belongs to
});

// #4698: a stop that lands while a chunk is in flight must still flush the tail
// and report both finals, in arrival order, each with its own accepted turn.
test("inflight stop plus tail keeps provider finals in order",async()=>{
  const x=setup();await x.settle();
  x.recorder().requestData();
  x.time(5000);x.level(.3);x.timers[0](); // speech started
  x.time(6500);x.level(0);x.timers[0](); // silence after the min chunk
  await x.settle();assert.equal(x.posts.length,1);
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.turns.length,0); // the tail is not accepted ahead of its transcript
  x.resolve("첫 구간");await x.settle();
  assert.equal(x.posts.length,2);
  assert.deepEqual(x.finals.map(v=>v.text),["첫 구간"]);
  assert.equal(x.turns.length,1);
  x.resolve("마지막 구간");await x.settle();
  assert.deepEqual(x.finals.map(v=>v.text),["첫 구간","마지막 구간"]);
  assert.deepEqual(x.turns.map(v=>v.finalId),x.finals.map(v=>v.utteranceId));
});

// #4698: a cancelled run and a silent run must never look like a completed turn.
test("cancelled and silent stops emit no accepted turn",async()=>{
  const cancelled=setup();await cancelled.settle();
  cancelled.handle.stop("account-switch");await cancelled.settle();
  assert.equal(cancelled.turns.length,0);
  const silent=setup({empty:true});await silent.settle();
  silent.handle.stop("user-stopped");await silent.settle();
  assert.equal(silent.posts.length,0);
  assert.equal(silent.turns.length,0);
});

// #4698: a failed provider request is an error, never an accepted end-of-turn.
test("failed provider request emits no final and no accepted turn",async()=>{
  const x=setup();await x.settle();
  x.handle.stop("user-stopped");await x.settle();
  assert.equal(x.posts.length,1);
  x.fail();await x.settle();
  assert.equal(x.finals.length,0);
  assert.equal(x.turns.length,0);
  // The run already ended, so the failure is not surfaced as a live error and
  // certainly not as a completed turn: no false success either way.
  assert.equal(x.errors.length,0);
});
