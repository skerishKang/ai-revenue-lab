/* #3790 verified owner-selected model UI, explicit only, no silent fallback. */
(() => {
 "use strict";
 const select=document.getElementById("clawVerifiedModelSelect");
 const manual=document.getElementById("clawModelIdInput");
 const status=document.getElementById("clawVerifiedModelHint");
 if(!select||!manual||!status)return;
 const IDS=new Set(["google/gemini-3.1-flash-lite","google/gemini-3.5-flash-lite",
   "google/gemma-4-26b-a4b-it","google/gemma-4-31b-it"]);
 const PROVEN="google/gemini-3.5-flash-lite";
 const tr=key=>window.__padiemLocale?.text?.(key)||key;
 let seq=0;
 function clear(){select.replaceChildren();const o=document.createElement("option");o.value="";
  o.textContent=tr("claw-verified-model-placeholder");select.appendChild(o);select.value="";}
 function valid(data){return data&&data.ok===true&&data.scope==="owner_confirmed_google_subset"
  &&data.complete_inventory===false&&data.automatic_default===false
  &&Array.isArray(data.model_choices)&&data.model_choices.length===4
  &&new Set(data.model_choices.map(x=>x?.model_id)).size===4
  &&data.model_choices.every(x=>x&&IDS.has(x.model_id)&&x.owner_selected===true
    &&x.product_name_prefix==="파디엠플러스"&&typeof x.individual_model_name==="string"
    &&x.individual_model_name.length>0&&x.individual_model_name.length<100
    &&typeof x.customer_selectable==="boolean"
    &&x.customer_selectable===x.product_e2e_verified
    &&(!x.customer_selectable||x.model_id===PROVEN));}
 async function load(){const ticket=++seq;select.disabled=true;clear();status.textContent=tr("claw-verified-model-loading");
  try{const r=await fetch("/api/claw/verified-model-choices",{credentials:"same-origin",cache:"no-store"});
   if(!r.ok)throw Error("not_authenticated");const data=await r.json();
   if(!valid(data))throw Error("invalid_choices");if(ticket!==seq)return;
   for(const row of data.model_choices){const opt=document.createElement("option");opt.value=row.model_id;
    opt.disabled=!row.customer_selectable;
    opt.textContent=row.individual_model_name+(opt.disabled?" ("+tr("claw-verified-model-hold")+")":"");
    select.appendChild(opt);}
   select.disabled=false;
   const previous=Array.from(select.options).find(x=>!x.disabled&&x.value===manual.value);
   select.value=previous?.value||"";status.textContent=tr("claw-verified-model-ready");
  }catch(_){if(ticket!==seq)return;clear();status.textContent=tr("claw-verified-model-unavailable");}
 }
 select.addEventListener("change",()=>{const opt=select.selectedOptions?.[0];
  if(!opt||opt.disabled||select.value!==PROVEN)return;
  manual.value=select.value;manual.dispatchEvent(new Event("input",{bubbles:true}));});
 manual.addEventListener("input",()=>{const opt=Array.from(select.options).find(x=>!x.disabled&&x.value===manual.value);
  select.value=opt?.value||"";});
 select.addEventListener("focus",()=>void load());
 window.addEventListener("padiem:localechange",()=>void load());
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",load,{once:true});
 else void load();
})();
