(function(root,factory){
  const api=factory(root||globalThis);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){
    root.STORYMEMORY_PACK_REGISTRY_CONTRACT=api.STORYMEMORY_PACK_REGISTRY_CONTRACT;
    root.createStoryMemoryPackMarketplaceRuntime=api.createStoryMemoryPackMarketplaceRuntime;
    root.createStoryMemoryNeonPackRegistryProvider=api.createStoryMemoryNeonPackRegistryProvider;
    root.storyMemoryPackMarketplace=root.storyMemoryPackMarketplace||api.createStoryMemoryPackMarketplaceRuntime({
      universalRuntime:root.storyMemoryUniversalSource||null,
      storage:root.localStorage||null
    });
    if(root.document?.documentElement)root.document.documentElement.dataset.storymemoryMarketplace='v1.0.0';
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';

  const CONTRACT=Object.freeze({
    schema:'storymemory-pack-registry-1.0',version:'1.0.0',packSchema:'storymemory-precision-pack-1.0',
    visibility:['private','public','org'],pricing:['free','paid'],publication:['draft','pending_review','published','suspended'],
    trustTiers:['auto-generated','community-reviewed','curated','expert','official'],
    paidProcessingImplemented:false,sourceBodyInRegistry:false,sourceBodyInPackDefault:false
  });

  const VERIFIED=new Set(['curated','expert','official']);
  const lower=v=>String(v??'').trim().toLowerCase();
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const uniq=a=>[...new Set(a.filter(Boolean))];
  const nowIso=()=>new Date().toISOString();
  function normalizeTier(v){const x=lower(v).replace(/_/g,'-');return CONTRACT.trustTiers.includes(x)?x:'auto-generated'}
  function normalizeListing(input={}){
    const packId=String(input.packId||input.pack_id||input.id||'').trim();
    if(!packId)throw new Error('PACK_REGISTRY_PACK_ID_REQUIRED');
    const visibility=lower(input.visibility||'private');
    const pricingMode=lower(input.pricingMode||input.pricing_mode||'free');
    const publicationStatus=lower(input.publicationStatus||input.publication_status||'draft');
    if(!CONTRACT.visibility.includes(visibility))throw new Error('PACK_REGISTRY_VISIBILITY_INVALID');
    if(!CONTRACT.pricing.includes(pricingMode))throw new Error('PACK_REGISTRY_PRICING_INVALID');
    if(!CONTRACT.publication.includes(publicationStatus))throw new Error('PACK_REGISTRY_PUBLICATION_INVALID');
    const sourceTextIncluded=input.sourceTextIncluded===true||input.source_text_included===true||input.rights?.sourceTextIncluded===true;
    if(sourceTextIncluded)throw new Error('PACK_PUBLICATION_SOURCE_BODY_FORBIDDEN');
    const versions=(Array.isArray(input.versions)?input.versions:input.version?[input.version]:[]).map(v=>normalizeVersion(v,packId));
    const attestations=(Array.isArray(input.attestations)?input.attestations:[]).map(a=>normalizeAttestation(a,packId));
    const listing={
      schema:CONTRACT.schema,packId,name:String(input.name||packId),packType:lower(input.packType||input.pack_type||input.kind||'companion'),
      creatorId:String(input.creatorId||input.creator_id||input.creator||'unknown'),publisherName:String(input.publisherName||input.publisher_name||''),summary:String(input.summary||''),
      visibility,pricingMode,publicationStatus,latestVersion:String(input.latestVersion||input.latest_version||versions[0]?.version||''),
      sourceTextIncluded:false,rightsDeclaration:clone(input.rightsDeclaration||input.rights_declaration||input.rights||{}),
      compatibilitySummary:clone(input.compatibilitySummary||input.compatibility_summary||input.compatibility||{}),permissions:clone(input.permissions||{}),
      processingDisclosure:clone(input.processingDisclosure||input.processing_disclosure||{}),listingMetadata:clone(input.listingMetadata||input.listing_metadata||input.metadata||{}),
      versions,attestations,createdAt:input.createdAt||input.created_at||null,updatedAt:input.updatedAt||input.updated_at||null
    };
    if(listing.visibility==='private'&&listing.publicationStatus==='published')throw new Error('PRIVATE_PACK_CANNOT_BE_PUBLICATION_PUBLISHED');
    return listing;
  }
  function normalizeVersion(input={},packId=''){
    return {packId:String(input.packId||input.pack_id||packId),version:String(input.version||'0.0.0'),schemaVersion:String(input.schemaVersion||input.schema_version||CONTRACT.packSchema),
      artifactUri:String(input.artifactUri||input.artifact_uri||''),artifactFingerprint:String(input.artifactFingerprint||input.artifact_fingerprint||''),
      declaredTrustTier:normalizeTier(input.declaredTrustTier||input.declared_trust_tier||input.trustTier),sourceMatchMode:lower(input.sourceMatchMode||input.source_match_mode||'exact-fingerprint'),
      compatibility:clone(input.compatibility||{}),rights:clone(input.rights||{}),changelog:String(input.changelog||''),parentVersion:input.parentVersion||input.parent_version||null,createdAt:input.createdAt||input.created_at||null};
  }
  function normalizeAttestation(input={},packId=''){
    return {id:String(input.id||''),packId:String(input.packId||input.pack_id||packId),version:String(input.version||''),verifierId:String(input.verifierId||input.verifier_id||''),
      verifierKind:lower(input.verifierKind||input.verifier_kind||'registry'),tier:normalizeTier(input.tier),verificationScope:clone(input.verificationScope||input.verification_scope||{}),
      sourceFingerprint:input.sourceFingerprint||input.source_fingerprint||null,status:lower(input.status||'valid'),issuedAt:input.issuedAt||input.issued_at||null,
      expiresAt:input.expiresAt||input.expires_at||null,revokedAt:input.revokedAt||input.revoked_at||null,metadata:clone(input.metadata||{}),trusted:input.trusted===true};
  }

  function createMemoryInstallStore(storage,key='storymemory.packInstalls.v1'){
    const mem=[];
    function read(){
      if(!storage)return mem;
      try{const x=JSON.parse(storage.getItem(key)||'[]');return Array.isArray(x)?x:[]}catch(_){return []}
    }
    function write(rows){if(storage)try{storage.setItem(key,JSON.stringify(rows))}catch(_){}else{mem.splice(0,mem.length,...rows)}return rows}
    return {
      list:async()=>clone(read()),
      upsert:async row=>{const rows=read();const i=rows.findIndex(x=>x.packId===row.packId&&x.sourceIdentity===row.sourceIdentity);if(i>=0)rows[i]={...rows[i],...clone(row),updatedAt:nowIso()};else rows.push({...clone(row),updatedAt:nowIso()});write(rows);return clone(i>=0?rows[i]:rows[rows.length-1])},
      remove:async(packId,sourceIdentity)=>{const rows=read().filter(x=>!(x.packId===packId&&x.sourceIdentity===sourceIdentity));write(rows);return true}
    };
  }

  function createStoryMemoryNeonPackRegistryProvider({remoteAdapter,getUserId}={}){
    if(!remoteAdapter||typeof remoteAdapter.request!=='function')throw new Error('STORYMEMORY_REMOTE_ADAPTER_REQUIRED');
    const eq=v=>`eq.${v}`;
    const userId=async()=>{const value=typeof getUserId==='function'?await getUserId():getUserId;if(!value)throw new Error('PACK_INSTALL_USER_ID_REQUIRED');return String(value)};
    async function list(){
      const [registry,versions,attestations]=await Promise.all([
        remoteAdapter.request('pack_registry',{query:{select:'pack_id,name,pack_type,creator_id,publisher_name,summary,visibility,pricing_mode,publication_status,latest_version,source_text_included,rights_declaration,compatibility_summary,permissions,processing_disclosure,listing_metadata,created_at,updated_at',publication_status:eq('published'),visibility:eq('public'),order:'updated_at.desc',limit:200}}),
        remoteAdapter.request('pack_versions',{query:{select:'pack_id,version,schema_version,artifact_uri,artifact_fingerprint,declared_trust_tier,source_match_mode,compatibility,rights,changelog,parent_version,created_at',limit:500}}),
        remoteAdapter.request('pack_attestations',{query:{select:'id,pack_id,version,verifier_id,verifier_kind,tier,verification_scope,source_fingerprint,status,issued_at,expires_at,revoked_at,metadata',status:eq('valid'),limit:500}})
      ]);
      const vs=Array.isArray(versions)?versions:[],ats=Array.isArray(attestations)?attestations:[];
      return (Array.isArray(registry)?registry:[]).map(r=>({...r,versions:vs.filter(v=>v.pack_id===r.pack_id),attestations:ats.filter(a=>a.pack_id===r.pack_id).map(a=>({...a,trusted:true}))}));
    }
    const installProvider={
      async list(){return remoteAdapter.request('pack_installs',{query:{select:'pack_id,version,source_identity,source_fingerprint,workspace_key,install_status,auto_update,settings,attached_at,detached_at,updated_at',order:'updated_at.desc',limit:200}})},
      async upsert(row){const uid=await userId();const body={user_id:uid,pack_id:row.packId,version:row.version||'1.0.0',source_identity:row.sourceIdentity,source_fingerprint:row.sourceFingerprint||null,workspace_key:row.workspaceKey||null,install_status:row.installStatus||'installed',auto_update:row.autoUpdate===true,settings:row.settings||{},detached_at:row.detachedAt||null,updated_at:row.updatedAt||nowIso()};const rows=await remoteAdapter.request('pack_installs',{method:'POST',query:{on_conflict:'user_id,pack_id,source_identity'},body,prefer:'resolution=merge-duplicates,return=representation'});return Array.isArray(rows)?rows[0]||body:body},
      async remove(packId,sourceIdentity){await userId();await remoteAdapter.request('pack_installs',{method:'DELETE',query:{pack_id:eq(packId),source_identity:eq(sourceIdentity)},prefer:'return=minimal'});return true}
    };
    return Object.freeze({list,installProvider});
  }

  function createStoryMemoryPackMarketplaceRuntime({universalRuntime=null,storage=null,artifactLoader=null,registryProvider=null,installProvider=null}={}){
    let runtime=universalRuntime||root.storyMemoryUniversalSource||null;
    let loader=typeof artifactLoader==='function'?artifactLoader:null;
    let provider=registryProvider&&typeof registryProvider==='object'?registryProvider:null;
    let installs=installProvider&&typeof installProvider==='object'?installProvider:createMemoryInstallStore(storage||root.localStorage||null);
    const catalog=new Map();
    const listeners=new Set();
    function emit(type,data={}){const evt={type,at:nowIso(),...clone(data)};for(const fn of listeners){try{fn(evt)}catch(_){}}return evt}
    function onChange(fn){if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn)}
    function setUniversalRuntime(x){runtime=x||null;wireVerifier();return Boolean(runtime)}
    function setArtifactLoader(fn){loader=typeof fn==='function'?fn:null;return Boolean(loader)}
    function setRegistryProvider(x){provider=x&&typeof x==='object'?x:null;return Boolean(provider)}
    function setInstallProvider(x){installs=x&&typeof x==='object'?x:createMemoryInstallStore(storage||root.localStorage||null);return true}
    function replaceCatalog(rows=[]){catalog.clear();for(const row of rows){const n=normalizeListing(row);catalog.set(n.packId,n)}emit('CATALOG_REPLACED',{count:catalog.size});return listCatalog()}
    function mergeCatalog(rows=[]){for(const row of rows){const n=normalizeListing(row);catalog.set(n.packId,n)}emit('CATALOG_MERGED',{count:catalog.size});return listCatalog()}
    function listCatalog(){return [...catalog.values()].map(clone)}
    async function refresh(options={}){
      if(provider?.list){const rows=await provider.list(options);replaceCatalog(Array.isArray(rows)?rows:rows?.rows||[])}
      else if(options.url&&typeof fetch==='function'){const r=await fetch(options.url,{credentials:'same-origin'});if(!r.ok)throw new Error(`PACK_REGISTRY_FETCH_FAILED:${r.status}`);const json=await r.json();replaceCatalog(Array.isArray(json)?json:json.listings||[])}
      return listCatalog();
    }
    function getListing(packId){const x=catalog.get(String(packId));return x?clone(x):null}
    function getVersion(listing,version=null){if(!listing)return null;const wanted=String(version||listing.latestVersion||'');return listing.versions.find(v=>v.version===wanted)||listing.versions[0]||null}
    function activeAttestation(listing,version,source=null){
      const now=Date.now();const candidates=listing.attestations.filter(a=>a.version===version.version&&a.status==='valid'&&!a.revokedAt&&(!a.expiresAt||Date.parse(a.expiresAt)>now));
      const valid=candidates.filter(a=>{
        if(a.sourceFingerprint&&source?.fingerprint&&String(a.sourceFingerprint)!==String(source.fingerprint))return false;
        return a.trusted===true;
      }).sort((a,b)=>CONTRACT.trustTiers.indexOf(b.tier)-CONTRACT.trustTiers.indexOf(a.tier));
      return valid[0]||null;
    }
    function sourceCompatible(source,listing,version=null){
      const v=getVersion(listing,version);if(!v)return {compatible:false,reason:'PACK_VERSION_NOT_FOUND'};
      const c=v.compatibility||{};const mode=v.sourceMatchMode||'exact-fingerprint';
      const sid=String(source?.sourceId||source?.source_id||'');const fp=String(source?.fingerprint||source?.sourceFingerprint||'');const rev=String(source?.revision||source?.sourceRevision||'');
      const lang=lower(source?.language||source?.metadata?.language||'');const scheme=lower(source?.locatorScheme||source?.metadata?.locatorScheme||source?.structure?.locatorScheme||'');
      if(c.language&&lang&&lower(c.language)!==lang)return {compatible:false,reason:'PACK_SOURCE_LANGUAGE_MISMATCH'};
      if(c.locatorScheme&&scheme&&lower(c.locatorScheme)!==scheme)return {compatible:false,reason:'PACK_LOCATOR_SCHEME_MISMATCH'};
      if(mode==='exact-fingerprint'&&c.sourceFingerprint&&fp&&String(c.sourceFingerprint)!==fp)return {compatible:false,reason:'PACK_SOURCE_FINGERPRINT_MISMATCH'};
      if(mode==='source-id'&&c.sourceId&&String(c.sourceId)!==sid)return {compatible:false,reason:'PACK_SOURCE_ID_MISMATCH'};
      if(mode==='work-revision'){
        const workKey=String(source?.workKey||source?.metadata?.workKey||'');
        if(c.workKey&&String(c.workKey)!==workKey)return {compatible:false,reason:'PACK_WORK_KEY_MISMATCH'};
        if(c.sourceRevision&&rev&&String(c.sourceRevision)!==rev)return {compatible:false,reason:'PACK_SOURCE_REVISION_MISMATCH'};
      }
      return {compatible:true,reason:'PASS'};
    }
    function search(options={}){
      const q=lower(options.query||'');const source=options.source||null;const compatibleOnly=options.compatibleOnly===true;
      let rows=[...catalog.values()].filter(x=>{
        if(options.includePrivate!==true&&!(x.publicationStatus==='published'&&x.visibility==='public'))return false;
        if(options.packType&&x.packType!==lower(options.packType))return false;
        if(options.pricingMode&&x.pricingMode!==lower(options.pricingMode))return false;
        if(q){const hay=lower([x.name,x.summary,x.publisherName,x.creatorId,...(x.listingMetadata?.tags||[])].join(' '));if(!hay.includes(q))return false;}
        if(compatibleOnly&&source&&!sourceCompatible(source,x).compatible)return false;
        return true;
      });
      rows.sort((a,b)=>Number(Boolean(source&&sourceCompatible(source,b).compatible))-Number(Boolean(source&&sourceCompatible(source,a).compatible))||String(b.updatedAt||'').localeCompare(String(a.updatedAt||''))||a.name.localeCompare(b.name));
      return rows.map(x=>{const v=getVersion(x);const att=v?activeAttestation(x,v,source):null;return {...clone(x),compatibilityResult:source?sourceCompatible(source,x):null,effectiveTrustTier:att?.tier||'unverified',verified:Boolean(att&&VERIFIED.has(att.tier))}});
    }
    function validatePublication(listing){
      const x=normalizeListing(listing);const issues=[];
      if(x.sourceTextIncluded)issues.push('SOURCE_BODY_INCLUDED');
      if(x.visibility==='public'&&x.publicationStatus==='published'){
        if(!x.rightsDeclaration||Object.keys(x.rightsDeclaration).length===0)issues.push('RIGHTS_DECLARATION_REQUIRED');
        if(x.rightsDeclaration?.privateSource===true||x.rightsDeclaration?.containsPrivateData===true)issues.push('PRIVATE_SOURCE_PUBLICATION_FORBIDDEN');
      }
      return {pass:issues.length===0,issues,listing:x};
    }
    async function defaultArtifactLoader(uri){if(typeof fetch!=='function')throw new Error('PACK_ARTIFACT_LOADER_REQUIRED');const r=await fetch(uri,{credentials:'same-origin'});if(!r.ok)throw new Error(`PACK_ARTIFACT_FETCH_FAILED:${r.status}`);return r.json()}
    async function loadArtifact(listing,version){const fn=loader||defaultArtifactLoader;const pack=await fn(version.artifactUri,{listing:clone(listing),version:clone(version)});if(!pack||typeof pack!=='object')throw new Error('PACK_ARTIFACT_INVALID');if(String(pack.id||pack.packId||'')!==listing.packId)throw new Error('PACK_ARTIFACT_ID_MISMATCH');if(String(pack.version||pack.packVersion||'')!==version.version)throw new Error('PACK_ARTIFACT_VERSION_MISMATCH');if(pack.rights?.sourceTextIncluded===true)throw new Error('PACK_ARTIFACT_SOURCE_BODY_FORBIDDEN');return pack}
    function verifier({pack,source}){
      const listing=catalog.get(String(pack?.id||pack?.packId||''));if(!listing)return null;const v=getVersion(listing,String(pack?.version||''));if(!v)return null;
      const att=activeAttestation(listing,v,source);if(!att)return {trusted:false,effectiveTrustTier:'unverified',reason:'NO_TRUSTED_REGISTRY_ATTESTATION'};
      return {trusted:true,effectiveTrustTier:att.tier,trustTier:att.tier,attestationId:att.id||null,verifiedBy:[att.verifierKind,att.verifierId].filter(Boolean).join(':')||null,verificationScope:JSON.stringify(att.verificationScope||{}),registryPackId:listing.packId,registryVersion:v.version};
    }
    function wireVerifier(){if(runtime?.setPackVerifier)runtime.setPackVerifier(verifier)}
    wireVerifier();
    async function install(packId,sourceId,options={}){
      if(!runtime)throw new Error('UNIVERSAL_RUNTIME_REQUIRED');const listing=catalog.get(String(packId));if(!listing)throw new Error('PACK_LISTING_NOT_FOUND');
      if(!(listing.publicationStatus==='published'&&listing.visibility==='public')&&options.allowPrivate!==true)throw new Error('PACK_NOT_PUBLICLY_INSTALLABLE');
      if(listing.pricingMode==='paid'&&options.entitled!==true)throw new Error('PAID_ENTITLEMENT_REQUIRED_NOT_IMPLEMENTED');
      const source=runtime.getSource(String(sourceId));if(!source)throw new Error(`SOURCE_NOT_FOUND:${sourceId}`);const version=getVersion(listing,options.version);if(!version)throw new Error('PACK_VERSION_NOT_FOUND');
      const compat=sourceCompatible(source,listing,version.version);if(!compat.compatible)throw new Error(compat.reason);
      const pack=await loadArtifact(listing,version);const attached=runtime.attachPack(source.sourceId,pack);
      const row={packId:listing.packId,version:version.version,sourceIdentity:source.sourceId,sourceFingerprint:source.fingerprint||null,workspaceKey:options.workspaceKey||null,installStatus:'installed',autoUpdate:options.autoUpdate===true,settings:clone(options.settings||{}),attachedAt:nowIso()};
      if(installs?.upsert)await installs.upsert(row);emit('PACK_INSTALLED',{packId:listing.packId,sourceId:source.sourceId,version:version.version});return {listing:clone(listing),version:clone(version),attached,install:row};
    }
    async function detach(packId,sourceId){if(!runtime)throw new Error('UNIVERSAL_RUNTIME_REQUIRED');const ok=runtime.detachPack(String(sourceId),String(packId));if(installs?.upsert)await installs.upsert({packId:String(packId),sourceIdentity:String(sourceId),installStatus:'detached',detachedAt:nowIso()});emit('PACK_DETACHED',{packId:String(packId),sourceId:String(sourceId)});return ok}
    async function uninstall(packId,sourceId){if(!runtime)throw new Error('UNIVERSAL_RUNTIME_REQUIRED');try{runtime.detachPack(String(sourceId),String(packId))}catch(_){}if(installs?.remove)await installs.remove(String(packId),String(sourceId));emit('PACK_UNINSTALLED',{packId:String(packId),sourceId:String(sourceId)});return true}
    async function listInstalls(){return installs?.list?clone(await installs.list()):[]}
    async function restoreInstalls(options={}){
      if(!runtime)return [];const rows=await listInstalls();const out=[];
      for(const row of rows.filter(x=>x.installStatus==='installed')){try{if(runtime.listAttachedPacks(row.sourceIdentity).some(p=>p.id===row.packId)){out.push({row,status:'already-attached'});continue;}out.push({row,status:'deferred-artifact-load'})}catch(_){out.push({row,status:'source-not-loaded'})}}
      if(options.emit!==false)emit('INSTALL_STATE_RESTORED',{count:out.length});return out;
    }
    function status(){return {schema:CONTRACT.schema,version:CONTRACT.version,catalogCount:catalog.size,publicCount:[...catalog.values()].filter(x=>x.publicationStatus==='published'&&x.visibility==='public').length,providerInstalled:Boolean(provider),artifactLoaderInstalled:Boolean(loader),universalRuntimeInstalled:Boolean(runtime),paidProcessingImplemented:false}}
    return Object.freeze({contract:CONTRACT,replaceCatalog,mergeCatalog,listCatalog,refresh,getListing,search,sourceCompatible,validatePublication,install,detach,uninstall,listInstalls,restoreInstalls,setUniversalRuntime,setArtifactLoader,setRegistryProvider,setInstallProvider,onChange,status,normalizeListing});
  }

  return {STORYMEMORY_PACK_REGISTRY_CONTRACT:CONTRACT,createStoryMemoryPackMarketplaceRuntime,createStoryMemoryNeonPackRegistryProvider};
});
