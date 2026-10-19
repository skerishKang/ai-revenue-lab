/* #3790: Claw shares B14's owner-allowed, ready model list with B66. */
(() => {
 "use strict";
 const select=document.getElementById("clawVerifiedModelSelect");
 const manual=document.getElementById("clawModelIdInput");
 const status=document.getElementById("clawVerifiedModelHint");
 if(!select||!manual||!status)return;
 const tr=key=>window.__padiemLocale?.text?.(key)||key;
 const EXACT_ID=/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
 let seq=0;
 function clear(){select.replaceChildren();const o=document.createElement("option");o.value="";
  o.textContent=tr("claw-verified-model-placeholder");select.appendChild(o);select.value="";}
 function valid(data){return data&&data.ok===true&&data.scope==="b14_owner_allowed_live_ready"
  &&data.complete_inventory===true&&data.automatic_default===false
  &&Array.isArray(data.model_choices)&&data.model_choices.length<=256
  &&new Set(data.model_choices.map(x=>x?.model_id)).size===data.model_choices.length
  &&data.model_choices.every(x=>x&&typeof x.model_id==="string"&&EXACT_ID.test(x.model_id)
    &&["파디엠프리","파디엠플러스"].includes(x.product_name_prefix)
    &&typeof x.individual_model_name==="string"
    &&x.individual_model_name.length>0&&x.individual_model_name.length<=100
    &&x.customer_selectable===true);}
 async function load(){const ticket=++seq;select.disabled=true;clear();status.textContent=tr("claw-verified-model-loading");
  try{const tier=window.PadiemTierSelection?.get?.()||"free";
   const r=await fetch("/api/claw/verified-model-choices?tier="+encodeURIComponent(tier),{credentials:"same-origin",cache:"no-store"});
   if(!r.ok)throw Error("not_authenticated");const data=await r.json();
   if(!valid(data))throw Error("invalid_choices");if(ticket!==seq)return;
   for(const row of data.model_choices){const opt=document.createElement("option");opt.value=row.model_id;
    opt.textContent=row.individual_model_name;
    select.appendChild(opt);}
   select.disabled=data.model_choices.length===0;
   const previous=Array.from(select.options).find(x=>x.value&&x.value===manual.value);
   select.value=previous?.value||"";
   status.textContent=data.model_choices.length?tr("claw-verified-model-ready"):tr("claw-verified-model-unavailable");
  }catch(_){if(ticket!==seq)return;clear();select.disabled=true;status.textContent=tr("claw-verified-model-unavailable");}
 }
 select.addEventListener("change",()=>{
  if(!select.value||!Array.from(select.options).some(o=>o.value===select.value))return;
  manual.value=select.value;manual.dispatchEvent(new Event("input",{bubbles:true}));
 });
 manual.addEventListener("input",()=>{
  const opt=Array.from(select.options).find(x=>x.value&&x.value===manual.value);
  select.value=opt?.value||"";
 });
 window.addEventListener("padiem:auth-state",event=>{
  if(event.detail?.authenticated===true){void load();return;}
  ++seq;clear();select.disabled=true;
  manual.value=""; // session revoked: never reuse stale explicit model
  status.textContent=tr("claw-verified-model-unavailable");
 });
 window.addEventListener("padiem:tierchange",()=>{manual.value="";void load();});
 window.addEventListener("padiem:localechange",()=>void load());
 if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",load,{once:true});
 else void load();
})();
