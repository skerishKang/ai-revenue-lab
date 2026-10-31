(function(root){
  'use strict';
  const d=root.document;if(!d||!root.storyMemoryAutoPack)return;
  const auto=root.storyMemoryAutoPack,rt=root.storyMemoryUniversalSource;
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  function activeSource(){const pos=rt?.getPosition?.();return pos?.sourceId?rt.getSource(pos.sourceId):null}
  function lastQuestion(){const input=d.getElementById('askInput');if(input?.value.trim())return input.value.trim();const users=[...d.querySelectorAll('#chatThread .msg.user p')];return users.at(-1)?.textContent?.trim()||''}
  function mount(){
    const host=d.getElementById('sourceTrustControl')||d.querySelector('#reader .ai-panel');if(!host||d.getElementById('autoPackLaunch'))return;
    const launch=d.createElement('button');launch.type='button';launch.id='autoPackLaunch';launch.className='auto-pack-launch';launch.textContent='PRECISION · 정확도 높이기';host.appendChild(launch);
    const panel=d.createElement('section');panel.id='autoPackPanel';panel.className='auto-pack-panel';panel.hidden=true;panel.innerHTML=`<div class="auto-pack-head"><strong>PRECISION UPGRADE</strong><small>기본 Harness가 부족할 때만 PRIVATE Pack 생성</small></div><label>실패/반복 질문<input id="autoPackQuestion" type="text" placeholder="정확도를 높일 질문"></label><div class="auto-pack-mode"><label><input type="radio" name="autoPackMode" value="quick" checked> Quick / Auto</label><label><input type="radio" name="autoPackMode" value="deep"> Deep · 명시적 심층</label></div><label>확인된 교정어 <input id="autoPackAlias" type="text" placeholder="예: 헬렌 → 헬레네, Helen"></label><button type="button" id="autoPackGenerate">PRIVATE PACK 생성·검증</button><div id="autoPackStatus" class="auto-pack-status">자동 공개하지 않습니다. 개선이 측정되지 않으면 Pack을 유지하지 않습니다.</div><div id="autoPackResult" class="auto-pack-result"></div>`;host.appendChild(panel);
    launch.onclick=()=>{panel.hidden=!panel.hidden;if(!panel.hidden){const q=d.getElementById('autoPackQuestion');if(q&&!q.value)q.value=lastQuestion()}};
    d.getElementById('autoPackGenerate').onclick=async()=>{
      const status=d.getElementById('autoPackStatus'),result=d.getElementById('autoPackResult');const src=activeSource();const question=d.getElementById('autoPackQuestion')?.value.trim()||lastQuestion();const mode=d.querySelector('input[name="autoPackMode"]:checked')?.value||'quick';
      if(!src||!question){status.textContent='현재 Source와 질문이 필요합니다.';return}
      const raw=d.getElementById('autoPackAlias')?.value.trim()||'';let confirmedAliases=[];if(raw.includes('→')){const [from,to]=raw.split('→');confirmedAliases=[{from:from.trim(),to:to.split(',').map(x=>x.trim()).filter(Boolean)}]}
      status.textContent='현재 Source 근거로 before/after를 측정하고 있습니다…';result.innerHTML='';
      try{const pos=rt.getPosition();const out=await auto.generate({sourceId:src.sourceId,question,locator:pos?.locator||null,mode,deepConfirmed:mode==='deep',explicitRequest:true,confirmedAliases,autoAttach:true});
        if(out.status==='REJECTED_NO_IMPROVEMENT'){status.textContent='측정 가능한 개선이 없어 Pack을 유지하지 않았습니다.';result.innerHTML='<p>Source와 Memory는 변경되지 않았습니다.</p>';return}
        status.textContent='PRIVATE Pack을 연결했습니다. 공개 Marketplace에는 올라가지 않았습니다.';result.innerHTML=`<strong>${esc(out.pack?.name||'Generated Pack')}</strong><p>${esc(out.pack?.id||'')}</p><p>Before ${esc(out.before?.relevantCount)} → After ${esc(out.after?.relevantCount)} · Δ score ${esc(out.delta?.deltaTopScore)}</p><p>AUTO-GENERATED · PRIVATE · UNVERIFIED</p>`;
        try{root.storyMemoryRefreshPackMarketplace?.()}catch(_){ }
      }catch(error){const msg=String(error?.message||error);status.textContent=msg==='AUTO_PACK_GENERATOR_PROVIDER_REQUIRED'?'AI Pack 생성 provider가 아직 연결되지 않았습니다. 확인된 교정어를 입력하면 provider 없이도 안전한 Search Pack을 만들 수 있습니다.':`Pack 생성 실패: ${msg}`}
    };
  }
  if(d.readyState==='loading')d.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})(typeof globalThis!=='undefined'?globalThis:this);
