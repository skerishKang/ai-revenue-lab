const fs=require('fs'), path=require('path'), assert=require('node:assert/strict');
(async()=>{
  const src=fs.readFileSync(path.join(__dirname,'public/_worker.js'),'utf8');
  const worker=(await import('data:text/javascript;base64,'+Buffer.from(src).toString('base64'))).default;
  const packet={version:'1',mode:'storymemory_bounded_companion',source_scope:'ceiling_filtered',
    diagnostics:{boundary_available:true,spoiler_policy:'hard_no_future'},
    co_reader_decision:{decision:'ALLOW',reason:'WITHIN_CEILING'},
    reader_context:{authoritative_reader:true,current_work_key:'bible-web'},
    reading_progress:{furthest_read_locator:'bible:web:ACT:9:5',knowledge_ceiling_locator:'bible:web:ACT:9:5'},
    source_passages:[{canonical_locator:'bible:web:ACT:9:3',text:'A light shone around Saul.'}]};
  const req=()=>new Request('https://test.invalid/api/storymemory-ai',{method:'POST',
    headers:{'content-type':'application/json'},body:JSON.stringify({question:'What happened?',packet})});
  const env={PADIEM_INGRESS_CLIENT_SECRET:'x'.repeat(40)};
  for(const [input,expected,status] of [
    ['<thought>private\nreason</thought>Answer.','Answer.',200],
    ['Normal answer.\nUnchanged.','Normal answer.\nUnchanged.',200],
    ['<thought>unfinished private text',null,502],
    ['Answer.<thought>unfinished', 'Answer.',200],
    ['<THOUGHT>one</THOUGHT>Answer.<thought>two</thought>','Answer.',200],
  ]){
    global.fetch=async()=>Response.json({ok:true,answer:input,context_permission:{
      boundary_disposition:'permitted',context_filtered_count:0,context_allowed_count:1}});
    const r=await worker.fetch(req(),env), data=await r.json();
    assert.equal(r.status,status);
    if(expected!==null) assert.equal(data.answer,expected);
    else {assert.equal(data.error,'ingress_invalid_response'); assert.ok(!JSON.stringify(data).includes('private'));}
  }
  console.log('PASS: 5 worker response cases');
})().catch(e=>{console.error(e);process.exitCode=1});
