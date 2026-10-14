"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const {create}=require("../static/voice-live-turn-controller.js");

test("Mode 2 does not impose a 1024-turn normal-use cap", () => {
  let sent=0;let auth="a";
  const c=create({accountKey:"a",getAccountKey:()=>auth,
    getInFlight:()=>false,getCanSubmit:()=>true,
    commitText:()=>true,submit:()=>{sent++;return true;}});
  c.setMode("live");
  const generation=c.getState().sessionGeneration;
  let first=null;
  for(let i=0;i<1300;i++){
    const result=c.handleFinal({accountKey:"a",sessionGeneration:generation,
      accepted:true,endOfTurn:true,finalId:"genuine-final-"+i,text:"voice "+i});
    assert.equal(result.submitted,true,"turn "+i+" should never hit a quota");
    if(i===0)first={accountKey:"a",sessionGeneration:generation,
      accepted:true,endOfTurn:true,finalId:"genuine-final-"+i,text:"voice "+i};
    assert.equal(c.markAnswerSettled({accountKey:"a",finalKey:result.finalKey}).ok,true);
  }
  assert.equal(sent,1300);
  assert.equal(c.handleFinal(first).reason,"duplicate");
  assert.equal(sent,1300);
});
