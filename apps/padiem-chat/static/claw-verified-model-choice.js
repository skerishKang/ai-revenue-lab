/* #6828: Claw shows only the PADIEM grade. No model picker stays.
 * The grade line stays out of the composer flow while the grade is ready;
 * it appears only when the grade status needs attention. */
(() => {
 "use strict";
 const status=document.getElementById("clawVerifiedModelHint");
 if(!status)return;
 const line=status.closest(".claw-model-choice");
 const tr=key=>window.__padiemLocale?.text?.(key)||key;
 let seq=0;
 // The grade readiness line is not first-screen content when the grade is
 // ready, and the answer changes only with the grade. A short in-memory window
 // (per page, never shared between accounts) stops the auth, tier and locale
 // notifications from repeating the same GET.
 const CACHE_MS=30000;
 let cachedTier="",cachedAt=0,cachedAvailable=false;
 let inflightTier="",inflight=null;
 const GRADE_LABEL={free:"Padiem Free",plus:"Padiem Plus",pro:"Padiem Pro",max:"Padiem Max",admin:"Padiem Admin"};
 function selectedGrade(){
   const tier=String(window.PadiemTierSelection?.get?.()||"free").toLowerCase();
   return GRADE_LABEL[tier]?tier:"free";
 }
 function valid(data,tier){return data&&data.ok===true&&data.scope==="b14_tier_ready"
  &&data.complete_inventory===true&&data.automatic_default===true
  &&data.tier===tier&&typeof data.available==="boolean"
  &&!Object.prototype.hasOwnProperty.call(data,"model_choices");}
 function report(available){
   if(available){status.textContent="";line&&line.setAttribute("hidden","");return;}
   line&&line.removeAttribute("hidden");
   status.textContent=tr("claw-verified-model-unavailable");
 }
 function reset(){status.textContent="";line&&line.setAttribute("hidden","");}
 async function load(){if(window.PadiemAuthGate?.authenticated()===false)return;
   const tier=selectedGrade();
   if(cachedTier===tier&&Date.now()-cachedAt<CACHE_MS){report(cachedAvailable);return;}
   if(inflight&&inflightTier===tier)return inflight;
   const ticket=++seq;
   inflightTier=tier;
   const run=(async()=>{
    try{const r=await fetch("/api/claw/verified-model-choices?tier="+encodeURIComponent(tier),{credentials:"same-origin",cache:"no-store"});
     if(!r.ok)throw Error("not_authenticated");const data=await r.json();
     if(!valid(data,tier))throw Error("invalid_status");if(ticket!==seq)return;
     report(data.available);
     cachedTier=tier;cachedAt=Date.now();cachedAvailable=data.available;
   }catch(_){if(ticket!==seq)return;report(false);}
   })();
   const shared=run.finally(function(){if(inflight===shared)inflight=null;});
   inflight=shared;
   return shared;
 }
 window.addEventListener("padiem:auth-state",event=>{
  if(event.detail?.authenticated===true){void load();return;}
  // Signed out: the auth gate owns that guidance, so the grade line stays
  // out of the composer flow instead of reporting a status problem. The
  // window is per page, so an account change must not inherit it.
  ++seq;cachedTier="";cachedAt=0;inflight=null;inflightTier="";reset();
 });
 window.addEventListener("padiem:tierchange",()=>void load());
 window.addEventListener("padiem:localechange",()=>void load());
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",load,{once:true});
 else void load();
})();
