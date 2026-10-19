"use strict";
const test=require("node:test"), assert=require("node:assert/strict");
const vm=require("node:vm"),fs=require("node:fs"),path=require("node:path");
const script=fs.readFileSync(path.join(__dirname,"../static/owner-model-preview.js"),"utf8");
class El {
  constructor(tag="div"){this.tag=tag;this.children=[];this.handlers={};this.attrs={};this.textContent="";this.open=false;this.className="";this.focusCount=0;}
  addEventListener(k,fn){this.handlers[k]=fn;}
  setAttribute(k,v){this.attrs[k]=v;if(k==="open")this.open=true;}
  removeAttribute(k){delete this.attrs[k];if(k==="open")this.open=false;}
  append(...c){this.children.push(...c);}
  replaceChildren(...c){this.children=c;}
  querySelectorAll(sel){const found=[];function visit(el){for(const c of el.children){if(c.className===sel.slice(1))found.push(c);visit(c);}}visit(this);return found;}
  showModal(){this.open=true;}
  close(){this.open=false;this.handlers.close?.();}
  click(){this.handlers.click?.();}
  focus(){this.focusCount++;}
}
const names=["Gemini 3.1 Flash Lite","Gemini 3.5 Flash Lite","Gemma 4 26B","Gemma 4 31B"];
function payload(){return {scope:"owner_confirmed_google_subset",complete_inventory:false,execution_enabled:false,model_names:names.map((name,i)=>({
  model_id:["google/gemini-3.1-flash-lite","google/gemini-3.5-flash-lite","google/gemma-4-26b-a4b-it","google/gemma-4-31b-it"][i],product_name_prefix:"파디엠플러스",individual_model_name:name,owner_selected:true,customer_selectable:false
}))};}
function load(p) {
  const ids=["ownerModelPreviewOpen","ownerModelPreviewDialog","ownerModelPreviewClose","ownerModelPreviewList","ownerModelPreviewStatus"];
  const els=Object.fromEntries(ids.map(id=>[id,new El()]));
  const calls=[];
  vm.runInNewContext(script,{
    document:{getElementById:id=>els[id],createElement:t=>new El(t)},
    window:{__padiemLocale:{text:k=>({
      "owner-model-preview-loading":"loading","owner-model-preview-unavailable":"unavailable","owner-model-preview-hold":"not ready"
    })[k]||k},addEventListener:()=>{}},
    fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>p};}
  });
  return {els,calls};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test("model preview renders four confirmed name parts, never a selectable model",async()=>{
  const h=load(payload());h.els.ownerModelPreviewOpen.click();await flush();
  assert.equal(h.els.ownerModelPreviewDialog.open,true);
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].url,"/api/models/owner-name-preview");
  assert.equal(h.calls[0].options.method,"GET");assert.equal(h.calls[0].options.cache,"no-store");
  assert.equal(h.els.ownerModelPreviewList.children.length,4);
  h.els.ownerModelPreviewList.children.forEach((row,i)=>{
    assert.equal(row.tag,"li");
    assert.equal(row.children[0].children[0].textContent,"파디엠플러스");
    assert.equal(row.children[0].children[1].textContent,names[i]);
    assert.equal(row.children[1].textContent,"not ready");
    assert.equal(row.children.some(x=>x.tag==="button"),false);
  });
  h.els.ownerModelPreviewOpen.click();await flush();assert.equal(h.calls.length,1);
  h.els.ownerModelPreviewClose.click();
  assert.equal(h.els.ownerModelPreviewDialog.open,false);
  assert.equal(h.els.ownerModelPreviewOpen.attrs["aria-expanded"],"false");
});
test("falsely enabled backend payload is refused and cannot create choices",async()=>{
  const p=payload();p.execution_enabled=true;
  const h=load(p);h.els.ownerModelPreviewOpen.click();await flush();
  assert.equal(h.els.ownerModelPreviewList.children.length,0);
  assert.equal(h.els.ownerModelPreviewStatus.textContent,"unavailable");
});
test("close cancels stale in-flight model status painting",async()=>{
  const h=load(payload());h.els.ownerModelPreviewOpen.click();h.els.ownerModelPreviewClose.click();await flush();
  assert.equal(h.els.ownerModelPreviewDialog.open,false);
  assert.equal(h.els.ownerModelPreviewList.children.length,0);
});

test("unapproved model identity is not displayed even if backend claims approval",async()=>{
  const p=payload();p.model_names[0].model_id="google/unapproved-fixture";
  const h=load(p);h.els.ownerModelPreviewOpen.click();await flush();
  assert.equal(h.els.ownerModelPreviewList.children.length,0);
  assert.equal(h.els.ownerModelPreviewStatus.textContent,"unavailable");
});
