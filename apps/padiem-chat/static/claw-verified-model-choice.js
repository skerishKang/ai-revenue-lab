/* #6828: Claw shows only the PADIEM grade. No model picker stays. */
(() => {
 "use strict";
 const status=document.getElementById("clawVerifiedModelHint");
 if(!status)return;
 const tr=key=>window.__padiemLocale?.text?.(key)||key;
 let seq=0;
 const GRADE_LABEL={free:"Padiem Free",plus:"Padiem Plus",pro:"Padiem Pro",max:"Padiem Max",admin:"Padiem Admin"};
 function selectedGrade(){
   const tier=String(window.PadiemTierSelection?.get?.()||"free").toLowerCase();
   return GRADE_LABEL[tier]?tier:"free";
 }
 function valid(data,tier){return data&&data.ok===true&&data.scope==="b14_tier_ready"
  &&data.complete_inventory===true&&data.automatic_default===true
  &&data.tier===tier&&typeof data.available==="boolean"
  &&!Object.prototype.hasOwnProperty.call(data,"model_choices");}
 function report(tier,available){
   const label=GRADE_LABEL[tier]||tier;
   status.textContent=available?tr("claw-verified-model-ready").replace("{grade}",label):tr("claw-verified-model-unavailable");
 }
 async function load(){if(window.PadiemAuthGate?.authenticated()===false)return;const ticket=++seq;
   const tier=selectedGrade();
   try{const r=await fetch("/api/claw/verified-model-choices?tier="+encodeURIComponent(tier),{credentials:"same-origin",cache:"no-store"});
    if(!r.ok)throw Error("not_authenticated");const data=await r.json();
    if(!valid(data,tier))throw Error("invalid_status");if(ticket!==seq)return;
    report(tier,data.available);
  }catch(_){if(ticket!==seq)return;report(tier,false);}
 }
 window.addEventListener("padiem:auth-state",event=>{
  if(event.detail?.authenticated===true){void load();return;}
  ++seq;report(selectedGrade(),false);
 });
 window.addEventListener("padiem:tierchange",()=>void load());
 window.addEventListener("padiem:localechange",()=>void load());
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",load,{once:true});
 else void load();
})();
