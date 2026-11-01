(function(root,factory){
  const api=factory(root||globalThis);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){
    root.STORYMEMORY_PACK_ENTITLEMENT_CONTRACT=api.STORYMEMORY_PACK_ENTITLEMENT_CONTRACT;
    root.createStoryMemoryPackEntitlementRuntime=api.createStoryMemoryPackEntitlementRuntime;
    root.createStoryMemoryNeonPackEntitlementProvider=api.createStoryMemoryNeonPackEntitlementProvider;
    root.storyMemoryPackEntitlements=root.storyMemoryPackEntitlements||api.createStoryMemoryPackEntitlementRuntime({
      marketplaceRuntime:root.storyMemoryPackMarketplace||null,
      storage:root.localStorage||null
    });
    if(root.document?.documentElement)root.document.documentElement.dataset.storymemoryEntitlement='v1.0.0';
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';

  const CONTRACT=Object.freeze({
    schema:'storymemory-pack-entitlement-1.0',version:'1.0.0',marketplaceStage:'M6-boundary',
    livePaymentCollectionImplemented:false,directClientGrantAllowed:false,sourceKnowledgeMutationRequired:false,
    offerStatus:['active','inactive'],purchaseStatus:['intent','pending','paid','failed','cancelled','refunded','chargeback'],
    entitlementStatus:['active','revoked','refunded','chargeback','expired'],
    settlementStatus:['pending','eligible','held','paid','reversed'],
    entitlementScope:['pack','version']
  });
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const lower=v=>String(v??'').trim().toLowerCase();
  const nowIso=()=>new Date().toISOString();
  const toMinor=v=>Number.isFinite(Number(v))?Math.trunc(Number(v)):0;
  const safeText=(v,n=500)=>String(v??'').trim().slice(0,n);
  const randomId=p=>`${p}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  function createStore(storage,key){const mem=[];const read=()=>{if(!storage)return mem;try{const x=JSON.parse(storage.getItem(key)||'[]');return Array.isArray(x)?x:[]}catch(_){return []}};const write=rows=>{if(storage){try{storage.setItem(key,JSON.stringify(rows))}catch(_){}}else mem.splice(0,mem.length,...rows);return rows};return {list:()=>clone(read()),upsert:(row,match)=>{const rows=read();const i=rows.findIndex(match);if(i>=0)rows[i]={...rows[i],...clone(row)};else rows.push(clone(row));write(rows);return clone(i>=0?rows[i]:rows[rows.length-1])},clear:()=>write([])}}
  function normalizeOffer(input={}){
    const offerId=safeText(input.offerId||input.offer_id||input.id,180);if(!offerId)throw new Error('PACK_OFFER_ID_REQUIRED');
    const packId=safeText(input.packId||input.pack_id,220);if(!packId)throw new Error('PACK_OFFER_PACK_ID_REQUIRED');
    const currency=safeText(input.currency||'USD',3).toUpperCase();if(!/^[A-Z]{3}$/.test(currency))throw new Error('PACK_OFFER_CURRENCY_INVALID');
    const amountMinor=toMinor(input.amountMinor??input.amount_minor);if(amountMinor<1)throw new Error('PACK_OFFER_AMOUNT_INVALID');
    const status=lower(input.status||input.offer_status||'active');if(!CONTRACT.offerStatus.includes(status))throw new Error('PACK_OFFER_STATUS_INVALID');
    const accessScope=lower(input.accessScope||input.access_scope||'pack');if(!CONTRACT.entitlementScope.includes(accessScope))throw new Error('PACK_OFFER_ACCESS_SCOPE_INVALID');
    return {offerId,packId,currency,amountMinor,status,accessScope,version:input.version?String(input.version):null,license:clone(input.license||{}),refundPolicy:clone(input.refundPolicy||input.refund_policy||{}),metadata:clone(input.metadata||{})};
  }
  function normalizeEntitlement(input={}){
    const packId=safeText(input.packId||input.pack_id,220);if(!packId)throw new Error('PACK_ENTITLEMENT_PACK_ID_REQUIRED');
    const status=lower(input.status||input.entitlement_status||'active');if(!CONTRACT.entitlementStatus.includes(status))throw new Error('PACK_ENTITLEMENT_STATUS_INVALID');
    const scope=lower(input.accessScope||input.access_scope||'pack');if(!CONTRACT.entitlementScope.includes(scope))throw new Error('PACK_ENTITLEMENT_SCOPE_INVALID');
    return {entitlementId:safeText(input.entitlementId||input.entitlement_id||randomId('entitlement'),220),userId:safeText(input.userId||input.user_id,220),packId,version:input.version?String(input.version):null,accessScope:scope,status,startsAt:input.startsAt||input.starts_at||nowIso(),expiresAt:input.expiresAt||input.expires_at||null,revokedAt:input.revokedAt||input.revoked_at||null,sourcePurchaseId:input.sourcePurchaseId||input.source_purchase_id||null,reason:safeText(input.reason||'',500),verified:input.verified===true,metadata:clone(input.metadata||{})};
  }
  function activeEntitlement(e,at=new Date()){
    if(!e||e.status!=='active'||e.verified!==true)return false;
    if(e.expiresAt&&new Date(e.expiresAt).getTime()<=at.getTime())return false;
    if(e.startsAt&&new Date(e.startsAt).getTime()>at.getTime())return false;
    return true;
  }
  function createStoryMemoryNeonPackEntitlementProvider({remoteAdapter,getUserId}={}){
    if(!remoteAdapter||typeof remoteAdapter.request!=='function')throw new Error('STORYMEMORY_REMOTE_ADAPTER_REQUIRED');
    const eq=v=>`eq.${v}`;const uid=async()=>{const x=typeof getUserId==='function'?await getUserId():getUserId;if(!x)throw new Error('PACK_ENTITLEMENT_USER_ID_REQUIRED');return String(x)};
    return Object.freeze({
      async listOffers(packId=null){const q={select:'offer_id,pack_id,currency,amount_minor,offer_status,access_scope,version,license,refund_policy,metadata,created_at,updated_at',offer_status:eq('active'),order:'updated_at.desc',limit:200};if(packId)q.pack_id=eq(packId);return remoteAdapter.request('pack_offers',{query:q})},
      async listEntitlements(packId=null){await uid();const q={select:'entitlement_id,user_id,pack_id,version,access_scope,entitlement_status,starts_at,expires_at,revoked_at,source_purchase_id,reason,metadata,created_at,updated_at',order:'updated_at.desc',limit:200};if(packId)q.pack_id=eq(packId);return remoteAdapter.request('pack_entitlements',{query:q})},
      async listPurchases(packId=null){await uid();const q={select:'purchase_id,user_id,pack_id,offer_id,version,provider,provider_transaction_id,currency,amount_minor,purchase_status,receipt_reference,initiated_at,verified_at,updated_at,metadata',order:'updated_at.desc',limit:200};if(packId)q.pack_id=eq(packId);return remoteAdapter.request('pack_purchase_transactions',{query:q})},
      async createPurchaseIntent(){throw new Error('LIVE_PAYMENT_PROVIDER_NOT_CONNECTED')},
      async verifyPaymentEvent(){throw new Error('SERVER_PAYMENT_VERIFIER_REQUIRED')},
      async verifySettlementEvent(){throw new Error('SERVER_SETTLEMENT_VERIFIER_REQUIRED')},
      async restoreEntitlements(){return this.listEntitlements()}
    });
  }
  function createStoryMemoryPackEntitlementRuntime({marketplaceRuntime=null,storage=null,provider=null,clock=nowIso}={}){
    let market=marketplaceRuntime||root.storyMemoryPackMarketplace||null;
    let remote=provider&&typeof provider==='object'?provider:null;
    const offerStore=createStore(storage,'storymemory.packOffers.v1');
    const entitlementStore=createStore(storage,'storymemory.packEntitlements.v1');
    const purchaseStore=createStore(storage,'storymemory.packPurchases.v1');
    const settlementStore=createStore(storage,'storymemory.packSettlements.v1');
    const listeners=new Set();
    const emit=(type,data)=>{for(const fn of listeners)try{fn({type,data:clone(data),at:clock()})}catch(_){}};
    const onChange=fn=>{if(typeof fn==='function')listeners.add(fn);return()=>listeners.delete(fn)};
    const setMarketplace=x=>(market=x||null,Boolean(market));
    const setProvider=x=>(remote=x&&typeof x==='object'?x:null,Boolean(remote));
    function listing(packId){const x=market?.getListing?.(packId)||(market?.listCatalog?.()||[]).find(y=>y.packId===String(packId));if(!x)throw new Error('PACK_LISTING_NOT_FOUND');return x}
    function mergeOffers(rows=[]){for(const raw of rows){const o=normalizeOffer(raw);offerStore.upsert(o,x=>x.offerId===o.offerId)}return listOffers()}
    function listOffers(packId=null){return offerStore.list().filter(x=>!packId||x.packId===String(packId)).map(clone)}
    async function refreshOffers(packId=null){if(!remote?.listOffers)return listOffers(packId);const rows=await remote.listOffers(packId);mergeOffers(Array.isArray(rows)?rows:[]);return listOffers(packId)}
    function findOffer(packId,offerId=null){const rows=listOffers(packId).filter(x=>x.status==='active');const o=offerId?rows.find(x=>x.offerId===String(offerId)):rows[0];if(!o)throw new Error('PACK_ACTIVE_OFFER_NOT_FOUND');return o}
    function localEntitlements(packId=null){return entitlementStore.list().filter(x=>!packId||x.packId===String(packId)).map(clone)}
    async function refreshEntitlements(packId=null){if(!remote?.listEntitlements)return localEntitlements(packId);const rows=await remote.listEntitlements(packId);for(const raw of Array.isArray(rows)?rows:[]){const e=normalizeEntitlement({...raw,verified:true});entitlementStore.upsert(e,x=>x.entitlementId===e.entitlementId||(!e.entitlementId&&x.packId===e.packId))}return localEntitlements(packId)}
    async function checkAccess(packId,{version=null,refresh=false,at=new Date()}={}){
      const x=listing(packId);if(x.publicationStatus!=='published')return {allowed:false,reason:'PACK_NOT_PUBLISHED',packId:x.packId,pricingMode:x.pricingMode};
      if(x.pricingMode==='free')return {allowed:true,reason:'FREE_PUBLIC',packId:x.packId,pricingMode:'free',entitlementRequired:false};
      if(refresh)await refreshEntitlements(x.packId);
      const e=localEntitlements(x.packId).find(v=>activeEntitlement(v,at)&&(v.accessScope==='pack'||!version||v.version===version));
      return e?{allowed:true,reason:'PAID_ENTITLEMENT_ACTIVE',packId:x.packId,pricingMode:'paid',entitlementRequired:true,entitlement:clone(e)}:{allowed:false,reason:'PAID_ENTITLEMENT_REQUIRED',packId:x.packId,pricingMode:'paid',entitlementRequired:true};
    }
    async function createPurchaseIntent(packId,{offerId=null,version=null,metadata={}}={}){
      const x=listing(packId);if(x.pricingMode!=='paid')return {status:'NOT_REQUIRED',packId:x.packId,reason:'FREE_PUBLIC',accessGranted:true};
      if(!listOffers(x.packId).length)await refreshOffers(x.packId);const offer=findOffer(x.packId,offerId);
      const intent={intentId:randomId('purchase-intent'),packId:x.packId,offerId:offer.offerId,version:version||offer.version||x.latestVersion||null,currency:offer.currency,amountMinor:offer.amountMinor,status:'intent',requiresExternalProvider:true,accessGranted:false,metadata:{...clone(metadata),clientCannotGrantEntitlement:true},createdAt:clock()};
      if(!remote?.createPurchaseIntent){emit('PURCHASE_INTENT_CREATED',intent);return {...intent,providerConnected:false,action:'CONNECT_PAYMENT_PROVIDER'};}
      const providerIntent=await remote.createPurchaseIntent(clone(intent));
      if(providerIntent?.accessGranted===true||['paid','captured','settled'].includes(lower(providerIntent?.status)))throw new Error('PURCHASE_INTENT_CANNOT_GRANT_ACCESS');
      const out={...intent,providerConnected:true,providerIntent:clone(providerIntent||{})};emit('PURCHASE_INTENT_CREATED',out);return out;
    }
    async function reconcilePaymentEvent(event={}){
      if(!remote?.verifyPaymentEvent)throw new Error('SERVER_PAYMENT_VERIFIER_REQUIRED');
      const verified=await remote.verifyPaymentEvent(clone(event));if(!verified||verified.verified!==true)throw new Error('PAYMENT_EVENT_NOT_VERIFIED');
      const status=lower(verified.purchaseStatus||verified.status);if(!CONTRACT.purchaseStatus.includes(status))throw new Error('PAYMENT_STATUS_INVALID');
      const packId=safeText(verified.packId||event.packId,220);if(!packId)throw new Error('PAYMENT_PACK_ID_REQUIRED');
      const purchase={purchaseId:safeText(verified.purchaseId||randomId('purchase'),220),userId:safeText(verified.userId||'',220),packId,offerId:safeText(verified.offerId||'',180)||null,version:verified.version||null,provider:safeText(verified.provider||event.provider||'external',80),providerTransactionId:safeText(verified.providerTransactionId||'',220)||null,currency:safeText(verified.currency||'USD',3).toUpperCase(),amountMinor:Math.max(0,toMinor(verified.amountMinor)),purchaseStatus:status,receiptReference:safeText(verified.receiptReference||'',300)||null,verified:true,verifiedAt:verified.verifiedAt||clock(),metadata:{...clone(verified.metadata||{}),rawPaymentCredentialsStored:false}};
      purchaseStore.upsert(purchase,x=>x.purchaseId===purchase.purchaseId||(purchase.providerTransactionId&&x.provider===purchase.provider&&x.providerTransactionId===purchase.providerTransactionId));
      let entitlement=null;
      if(status==='paid'){
        entitlement=normalizeEntitlement({entitlementId:verified.entitlementId||randomId('entitlement'),userId:purchase.userId,packId,version:verified.entitlementVersion||purchase.version,accessScope:verified.accessScope||'pack',status:'active',sourcePurchaseId:purchase.purchaseId,startsAt:verified.startsAt||clock(),expiresAt:verified.expiresAt||null,reason:'provider-verified-purchase',verified:true,metadata:{provider:purchase.provider}});
        entitlementStore.upsert(entitlement,x=>x.packId===entitlement.packId&&(!entitlement.userId||x.userId===entitlement.userId));
      }else if(['refunded','chargeback','cancelled'].includes(status)){
        const existing=localEntitlements(packId)[0];if(existing){const mapped=status==='cancelled'?'revoked':status;entitlement=normalizeEntitlement({...existing,status:mapped,revokedAt:clock(),reason:`provider-${status}`,verified:true});entitlementStore.upsert(entitlement,x=>x.entitlementId===existing.entitlementId)}
      }
      emit('PAYMENT_RECONCILED',{purchase,entitlement});return {purchase:clone(purchase),entitlement:clone(entitlement),access:await checkAccess(packId,{version:purchase.version})};
    }
    async function restoreEntitlements(){
      if(!remote?.restoreEntitlements)throw new Error('ENTITLEMENT_RESTORE_PROVIDER_REQUIRED');
      const rows=await remote.restoreEntitlements();let imported=0;
      for(const raw of Array.isArray(rows)?rows:[]){if(raw.verified===false)continue;const e=normalizeEntitlement({...raw,verified:true});entitlementStore.upsert(e,x=>x.entitlementId===e.entitlementId||x.packId===e.packId);imported++}
      emit('ENTITLEMENTS_RESTORED',{imported});return {imported,entitlements:localEntitlements()};
    }
    function settlementPreview({packId,purchaseId,grossMinor,platformFeeMinor=0,currency='USD',creatorId=''}={}){
      const gross=Math.max(0,toMinor(grossMinor)),fee=Math.max(0,toMinor(platformFeeMinor));if(fee>gross)throw new Error('SETTLEMENT_FEE_EXCEEDS_GROSS');
      return {settlementId:randomId('settlement-preview'),packId:String(packId||''),purchaseId:String(purchaseId||''),creatorId:String(creatorId||''),currency:String(currency||'USD').toUpperCase(),grossMinor:gross,platformFeeMinor:fee,creatorNetMinor:gross-fee,settlementStatus:'pending',payoutReference:null,providerVerified:false,previewOnly:true};
    }
    async function reconcileSettlementEvent(event={}){
      if(!remote?.verifySettlementEvent)throw new Error('SERVER_SETTLEMENT_VERIFIER_REQUIRED');const verified=await remote.verifySettlementEvent(clone(event));if(!verified||verified.verified!==true)throw new Error('SETTLEMENT_EVENT_NOT_VERIFIED');
      const status=lower(verified.settlementStatus||verified.status);if(!CONTRACT.settlementStatus.includes(status))throw new Error('SETTLEMENT_STATUS_INVALID');
      if(status==='paid'&&!safeText(verified.payoutReference,300))throw new Error('SETTLEMENT_PAID_REFERENCE_REQUIRED');
      const row={settlementId:safeText(verified.settlementId||randomId('settlement'),220),packId:safeText(verified.packId,220),purchaseId:safeText(verified.purchaseId,220),creatorId:safeText(verified.creatorId,220),currency:safeText(verified.currency||'USD',3).toUpperCase(),grossMinor:Math.max(0,toMinor(verified.grossMinor)),platformFeeMinor:Math.max(0,toMinor(verified.platformFeeMinor)),creatorNetMinor:Math.max(0,toMinor(verified.creatorNetMinor)),settlementStatus:status,payoutReference:safeText(verified.payoutReference||'',300)||null,providerVerified:true,updatedAt:clock()};
      if(row.grossMinor!==row.platformFeeMinor+row.creatorNetMinor)throw new Error('SETTLEMENT_ARITHMETIC_INVALID');settlementStore.upsert(row,x=>x.settlementId===row.settlementId||x.purchaseId===row.purchaseId);emit('SETTLEMENT_RECONCILED',row);return clone(row);
    }
    function status(){return {schema:CONTRACT.schema,version:CONTRACT.version,marketplaceInstalled:Boolean(market),providerInstalled:Boolean(remote),offers:listOffers().length,entitlements:localEntitlements().length,purchases:purchaseStore.list().length,settlements:settlementStore.list().length,livePaymentCollectionImplemented:false,directClientGrantAllowed:false,sourceKnowledgeMutationRequired:false}}
    return Object.freeze({contract:CONTRACT,setMarketplace,setProvider,onChange,normalizeOffer,mergeOffers,listOffers,refreshOffers,localEntitlements,refreshEntitlements,checkAccess,createPurchaseIntent,reconcilePaymentEvent,restoreEntitlements,settlementPreview,reconcileSettlementEvent,status,activeEntitlement});
  }
  return {STORYMEMORY_PACK_ENTITLEMENT_CONTRACT:CONTRACT,createStoryMemoryPackEntitlementRuntime,createStoryMemoryNeonPackEntitlementProvider};
});
