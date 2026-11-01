(function(root,factory){
  const api=factory(root||globalThis);
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root){
    root.STORYMEMORY_PACK_VERIFICATION_CONTRACT=api.STORYMEMORY_PACK_VERIFICATION_CONTRACT;
    root.createStoryMemoryPackVerificationRuntime=api.createStoryMemoryPackVerificationRuntime;
    root.createStoryMemoryNeonPackVerificationProvider=api.createStoryMemoryNeonPackVerificationProvider;
    root.storyMemoryPackVerification=root.storyMemoryPackVerification||api.createStoryMemoryPackVerificationRuntime({
      universalRuntime:root.storyMemoryUniversalSource||null,
      marketplaceRuntime:root.storyMemoryPackMarketplace||null
    });
    if(root.document?.documentElement)root.document.documentElement.dataset.storymemoryPackVerification='v1.0.0';
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(root){
  'use strict';
  const CONTRACT=Object.freeze({
    schema:'storymemory-pack-verification-1.0',version:'1.0.0',programStage:'M7',
    programTiers:['expert','official'],curatedFallbackKinds:['registry','host'],
    verifierStatuses:['pending','active','suspended','revoked'],credentialStatuses:['pending','active','expired','revoked'],
    attestationStatuses:['valid','revoked','expired'],requiresExactPackVersion:true,requiresSourceFingerprint:true,
    trustNotInheritedAcrossVersion:true,trustNotInheritedAcrossFork:true,popularityCreatesTrust:false,ratingCreatesTrust:false,
    sourceBodyStored:false,knowledgeDbRequired:false
  });
  const clone=v=>v==null?v:JSON.parse(JSON.stringify(v));
  const lower=v=>String(v??'').trim().toLowerCase().replace(/_/g,'-');
  const nowIso=()=>new Date().toISOString();
  const asTime=v=>{const t=Date.parse(v||'');return Number.isFinite(t)?t:null};
  const nonEmptyObject=v=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).length>0;
  const tierRank=t=>({official:3,expert:2,curated:1}[lower(t)]||0);

  function normalizeProgramRow(input={}){
    return {
      attestationId:String(input.attestationId||input.attestation_id||input.id||''),
      packId:String(input.packId||input.pack_id||''),version:String(input.version||''),tier:lower(input.tier),
      sourceFingerprint:String(input.sourceFingerprint||input.source_fingerprint||''),verificationScope:clone(input.verificationScope||input.verification_scope||{}),
      attestationStatus:lower(input.attestationStatus||input.attestation_status||input.status||'valid'),issuedAt:input.issuedAt||input.issued_at||null,
      expiresAt:input.expiresAt||input.expires_at||null,revokedAt:input.revokedAt||input.revoked_at||null,
      verifierId:String(input.verifierId||input.verifier_id||''),verifierDisplayName:String(input.verifierDisplayName||input.verifier_display_name||''),
      verifierKind:lower(input.verifierKind||input.verifier_kind||''),verifierStatus:lower(input.verifierStatus||input.verifier_status||'active'),
      verifierOrganization:String(input.verifierOrganization||input.verifier_organization||''),
      credentialId:String(input.credentialId||input.credential_id||''),credentialType:String(input.credentialType||input.credential_type||''),
      credentialIssuer:String(input.credentialIssuer||input.credential_issuer||''),credentialStatus:lower(input.credentialStatus||input.credential_status||'active'),
      credentialValidFrom:input.credentialValidFrom||input.credential_valid_from||null,credentialValidUntil:input.credentialValidUntil||input.credential_valid_until||null,
      credentialAuthorityScope:clone(input.credentialAuthorityScope||input.credential_authority_scope||{}),requestId:String(input.requestId||input.request_id||''),
      requestStatus:lower(input.requestStatus||input.request_status||'approved'),artifactFingerprint:String(input.artifactFingerprint||input.artifact_fingerprint||''),
      metadata:clone(input.metadata||{})
    };
  }

  function createStoryMemoryNeonPackVerificationProvider({remoteAdapter}={}){
    if(!remoteAdapter||typeof remoteAdapter.request!=='function')throw new Error('STORYMEMORY_REMOTE_ADAPTER_REQUIRED');
    async function listProgram(){
      const rows=await remoteAdapter.request('pack_verification_public_state',{query:{select:'attestation_id,pack_id,version,tier,source_fingerprint,verification_scope,attestation_status,issued_at,expires_at,revoked_at,verifier_id,verifier_display_name,verifier_kind,verifier_status,verifier_organization,credential_id,credential_type,credential_issuer,credential_status,credential_valid_from,credential_valid_until,credential_authority_scope,request_id,request_status,artifact_fingerprint',limit:500}});
      return Array.isArray(rows)?rows:[];
    }
    async function listRequests(){
      const rows=await remoteAdapter.request('pack_verification_requests',{query:{select:'request_id,pack_id,version,requester_id,requested_tier,source_fingerprint,verification_scope,request_status,assigned_verifier_id,created_at,updated_at',order:'updated_at.desc',limit:200}});
      return Array.isArray(rows)?rows:[];
    }
    async function submitRequest(input={}){
      const body={pack_id:String(input.packId||''),version:String(input.version||''),requester_id:String(input.requesterId||''),requested_tier:lower(input.requestedTier),source_fingerprint:String(input.sourceFingerprint||''),verification_scope:clone(input.verificationScope||{}),request_status:'submitted'};
      if(!body.pack_id||!body.version||!body.requester_id||!CONTRACT.programTiers.includes(body.requested_tier)||!body.source_fingerprint||!nonEmptyObject(body.verification_scope))throw new Error('VERIFICATION_REQUEST_INVALID');
      const rows=await remoteAdapter.request('pack_verification_requests',{method:'POST',body,prefer:'return=representation'});return Array.isArray(rows)?rows[0]||body:body;
    }
    return Object.freeze({listProgram,listRequests,submitRequest});
  }

  function createStoryMemoryPackVerificationRuntime({universalRuntime=null,marketplaceRuntime=null,registryProvider=null,now=null}={}){
    let runtime=universalRuntime||root.storyMemoryUniversalSource||null;
    let market=marketplaceRuntime||root.storyMemoryPackMarketplace||null;
    let provider=registryProvider&&typeof registryProvider==='object'?registryProvider:null;
    let clock=typeof now==='function'?now:()=>Date.now();
    let rows=[];const listeners=new Set();
    const emit=(type,data={})=>{const evt={type,at:nowIso(),...clone(data)};for(const fn of listeners){try{fn(evt)}catch(_){}}return evt};
    const onChange=fn=>{if(typeof fn!=='function')return()=>{};listeners.add(fn);return()=>listeners.delete(fn)};
    function setUniversalRuntime(x){runtime=x||null;wireVerifier();return Boolean(runtime)}
    function setMarketplaceRuntime(x){market=x||null;return Boolean(market)}
    function setRegistryProvider(x){provider=x&&typeof x==='object'?x:null;return Boolean(provider)}
    function replaceProgram(input=[]){rows=(Array.isArray(input)?input:[]).map(normalizeProgramRow);wireVerifier();emit('VERIFICATION_PROGRAM_REPLACED',{count:rows.length});return listProgram()}
    function listProgram(){return rows.map(clone)}
    async function refresh(){if(provider?.listProgram)replaceProgram(await provider.listProgram());return listProgram()}

    function authorityAllows(row,listing){
      const scope=row.credentialAuthorityScope||{};
      if(Array.isArray(scope.tiers)&&scope.tiers.length&&!scope.tiers.map(lower).includes(row.tier))return false;
      if(Array.isArray(scope.packTypes)&&scope.packTypes.length&&listing?.packType&&!scope.packTypes.map(lower).includes(lower(listing.packType)))return false;
      if(Array.isArray(scope.packIds)&&scope.packIds.length&&!scope.packIds.map(String).includes(row.packId))return false;
      if(Array.isArray(scope.sourceFingerprints)&&scope.sourceFingerprints.length&&!scope.sourceFingerprints.map(String).includes(row.sourceFingerprint))return false;
      return true;
    }
    function evaluateProgramRow(row,pack,source){
      const listing=market?.getListing?.(row.packId)||null;const nowMs=Number(clock());const issues=[];
      if(!CONTRACT.programTiers.includes(row.tier))issues.push('PROGRAM_TIER_REQUIRED');
      if(row.packId!==String(pack?.id||pack?.packId||''))issues.push('ATTESTATION_PACK_MISMATCH');
      if(row.version!==String(pack?.version||pack?.packVersion||''))issues.push('ATTESTATION_VERSION_MISMATCH');
      if(row.attestationStatus!=='valid'||row.revokedAt)issues.push('ATTESTATION_NOT_VALID');
      const issued=asTime(row.issuedAt),expires=asTime(row.expiresAt);if(issued!==null&&issued>nowMs)issues.push('ATTESTATION_NOT_YET_VALID');if(expires===null||expires<=nowMs)issues.push('ATTESTATION_EXPIRED');
      if(!row.sourceFingerprint)issues.push('ATTESTATION_SOURCE_FINGERPRINT_REQUIRED');
      if(!source?.fingerprint||row.sourceFingerprint!==String(source.fingerprint))issues.push('ATTESTATION_SOURCE_FINGERPRINT_MISMATCH');
      if(!nonEmptyObject(row.verificationScope))issues.push('ATTESTATION_SCOPE_REQUIRED');
      if(row.verifierStatus!=='active')issues.push('VERIFIER_NOT_ACTIVE');
      if(!row.verifierId||!row.credentialId)issues.push('VERIFIER_CREDENTIAL_REQUIRED');
      if(row.credentialStatus!=='active')issues.push('CREDENTIAL_NOT_ACTIVE');
      const cFrom=asTime(row.credentialValidFrom),cUntil=asTime(row.credentialValidUntil);if(cFrom!==null&&cFrom>nowMs)issues.push('CREDENTIAL_NOT_YET_VALID');if(cUntil===null||cUntil<=nowMs)issues.push('CREDENTIAL_EXPIRED');
      if(row.requestStatus!=='approved'||!row.requestId)issues.push('APPROVED_REQUEST_REQUIRED');
      if(row.tier==='official'&&!['publisher','author','institution'].includes(row.verifierKind))issues.push('OFFICIAL_VERIFIER_KIND_INVALID');
      if(row.tier==='expert'&&!['expert','institution','publisher','author'].includes(row.verifierKind))issues.push('EXPERT_VERIFIER_KIND_INVALID');
      if(!authorityAllows(row,listing))issues.push('CREDENTIAL_AUTHORITY_SCOPE_MISMATCH');
      return {trusted:issues.length===0,issues,row:clone(row),listing:clone(listing)};
    }
    function curatedFallback(pack,source){
      const listing=market?.getListing?.(String(pack?.id||pack?.packId||''));if(!listing)return null;const nowMs=Number(clock());
      const candidates=(listing.attestations||[]).filter(a=>String(a.version)===String(pack?.version||'')&&lower(a.tier)==='curated'&&a.status==='valid'&&!a.revokedAt&&(!a.expiresAt||asTime(a.expiresAt)>nowMs)&&CONTRACT.curatedFallbackKinds.includes(lower(a.verifierKind))&&(!a.sourceFingerprint||String(a.sourceFingerprint)===String(source?.fingerprint||'')));
      if(!candidates.length)return null;const a=candidates[0];return {trusted:true,effectiveTrustTier:'curated',trustTier:'curated',attestationId:a.id||null,verifiedBy:[a.verifierKind,a.verifierId].filter(Boolean).join(':')||'registry',verificationScope:JSON.stringify(a.verificationScope||{}),program:'registry-curated'};
    }
    function resolve(pack,source){
      const packId=String(pack?.id||pack?.packId||''),version=String(pack?.version||pack?.packVersion||'');
      const candidates=rows.filter(r=>r.packId===packId&&r.version===version).map(r=>evaluateProgramRow(r,pack,source)).filter(x=>x.trusted).sort((a,b)=>tierRank(b.row.tier)-tierRank(a.row.tier));
      if(candidates.length){const x=candidates[0],r=x.row;return {trusted:true,effectiveTrustTier:r.tier,trustTier:r.tier,attestationId:r.attestationId,verifiedBy:[r.verifierKind,r.verifierDisplayName||r.verifierId].filter(Boolean).join(': '),verificationScope:JSON.stringify(r.verificationScope||{}),credentialId:r.credentialId,requestId:r.requestId,expiresAt:r.expiresAt,program:'expert-official'};}
      return curatedFallback(pack,source)||{trusted:false,effectiveTrustTier:'unverified',trustTier:'unverified',reason:'NO_VALID_EXPERT_OFFICIAL_ATTESTATION'};
    }
    function verifier({pack,source}){return resolve(pack,source)}
    function wireVerifier(){if(runtime?.setPackVerifier)runtime.setPackVerifier(verifier)}
    function getStatus(packId,version,source){
      const pseudo={id:String(packId),version:String(version)};const res=resolve(pseudo,source||null);const all=rows.filter(r=>r.packId===String(packId)&&r.version===String(version)).map(r=>evaluateProgramRow(r,pseudo,source||null));
      return {...res,packId:String(packId),version:String(version),programRows:all.map(x=>({trusted:x.trusted,issues:x.issues,row:x.row}))};
    }
    async function requestVerification(input={}){if(!provider?.submitRequest)throw new Error('VERIFICATION_REQUEST_PROVIDER_REQUIRED');return provider.submitRequest(input)}
    function status(){return {schema:CONTRACT.schema,version:CONTRACT.version,programRows:rows.length,providerInstalled:Boolean(provider),universalRuntimeInstalled:Boolean(runtime),marketplaceRuntimeInstalled:Boolean(market),trustNotInheritedAcrossVersion:true,trustNotInheritedAcrossFork:true,popularityCreatesTrust:false,ratingCreatesTrust:false}}
    wireVerifier();
    return Object.freeze({contract:CONTRACT,replaceProgram,listProgram,refresh,evaluateProgramRow,getStatus,verifier,wireVerifier,requestVerification,setUniversalRuntime,setMarketplaceRuntime,setRegistryProvider,onChange,status});
  }
  return {STORYMEMORY_PACK_VERIFICATION_CONTRACT:CONTRACT,createStoryMemoryPackVerificationRuntime,createStoryMemoryNeonPackVerificationProvider};
});
