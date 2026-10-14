"use strict";
/* PUBLIC DEMO — in-memory synthetic data, no persistence and no network calls.
 * This file runs before app.js. It deliberately exposes no SIP, PSTN, WebRTC,
 * external API, account access or payment functionality.
 */
(() => {
  const examples = [
    {script_id:"sample-general",title:"일반 문의",destination:"고객센터 (가상)",
      goal:"이용 내역을 확인하고 필요한 절차를 알려줘.",questions:"필요 서류와 신청 절차는 무엇인가요?",
      notes:"개인정보 확인이나 유료 계약 변경은 진행하지 않습니다.",revision:1,built_in:true},
    {script_id:"sample-vendor",title:"거래처 확인",destination:"거래처 (가상)",
      goal:"현재 주문 건의 진행 상태와 예상 완료 시점을 확인해 줘.",questions:"현재 진행 단계와 예상 완료일은 언제인가요?",
      notes:"추가 발주나 계약 변경은 하지 않습니다.",revision:1,built_in:true},
    {script_id:"sample-booking",title:"예약 문의",destination:"예약센터 (가상)",
      goal:"예약 가능한 시간과 필요한 준비 사항을 확인해 줘.",questions:"가능한 날짜와 준비 사항을 확인해 주세요.",
      notes:"예약 확정이나 결제는 진행하지 않습니다.",revision:1,built_in:true}
  ];
  const builtIn = examples.length;
  const stages = {
    standard:[["DIALING",2,900],["IVR",3,1000],["HOLD",20,2800],["CONSULTING",5,1200],["COMPLETED",0,0]],
    extended:[["DIALING",2,900],["IVR",3,1000],["HOLD",55,4500],["CONSULTING",5,1200],["COMPLETED",0,0]],
    no_answer:[["DIALING",4,2000],["NO_ANSWER",0,0]],
    verification:[["DIALING",2,900],["IVR",3,1000],["HOLD",14,1700],["CONSULTING",1,900],["AUTH_REQUIRED",0,0]]
  };
  const labels = {DIALING:"가상 발신 연결 시도",IVR:"가상 ARS 안내",HOLD:"가상 상담원 대기",
    CONSULTING:"가상 상담 진행",COMPLETED:"모의 완료",NO_ANSWER:"가상 무응답",
    AUTH_REQUIRED:"본인확인 필요(모의)",CANCELLED:"모의 작업 취소"};
  const terminal = new Set(["COMPLETED","NO_ANSWER","AUTH_REQUIRED","CANCELLED"]);
  const tasks = new Map();
  const byRequest = new Map();
  const scripts = [...examples];
  const now = () => performance.now();
  const fail = (message) => { throw Error(message); };
  const valid = (value, min, max) => typeof value === "string" && value.trim().length >= min &&
    value.trim().length <= max && !/[\u0000-\u001F]/.test(value);
  const parseBody = init => { try{return JSON.parse(init.body || "{}")}catch{return fail("잘못된 데이터입니다")} };
  const getScript = id => scripts.find(s => s.script_id === id) || fail("해당 대본을 찾지 못했습니다");
  const taskId = () => crypto.randomUUID().replaceAll("-","");
  const makeSnapshot = task => {
    if(task.frozen) return {...task.frozen};
    let elapsed = Math.max(0, now() - task.started), passed = 0, simulated = 0, index = 0;
    const steps = stages[task.scenario];
    let phase = steps.at(-1)[0];
    for(let i=0;i<steps.length;i++){
      const [name,minutes,ms] = steps[i]; index=i;
      if(elapsed < passed + ms){
        phase=name;
        simulated += Math.round(minutes * Math.max(0,(elapsed-passed)/ms));
        break;
      }
      simulated += minutes;
      passed += ms;
    }
    const finished = terminal.has(phase);
    let result = null;
    if(finished){
      result = phase==="COMPLETED"?"모의 전화 업무 완료. 실제 상담이 아닙니다.":
        phase==="NO_ANSWER"?"모의 통화 무응답. 실제 전화를 걸지 않았습니다.":
        "가상 본인확인 요청으로 업무를 보류했습니다.";
    }
    return {
      task_id:task.id, request_id:task.request_id,
      created_at:task.created_at, source:task.source,
      goal:task.goal,destination:task.destination,scenario:task.scenario,
      questions:task.questions, notes:task.notes, script_id:task.script_id,
      state:phase, stage_index:index, stage_total:steps.length,
      simulated_elapsed_minutes:simulated,
      simulated_connected_minutes:Math.max(0,simulated-steps[0][1]),
      terminal:finished, result, network_calls:0, real_charges:0
    };
  };
  const snapshotList = () => [...tasks.values()].reverse().map(makeSnapshot);
  const asTimeline = snap => {
    const steps=stages[snap.scenario], rows=[];
    let started=0;
    for(let i=0;i<=snap.stage_index;i++){
      const [name, minutes] = steps[i];
      const duration = i<snap.stage_index || snap.terminal && name===snap.state
        ?minutes:Math.max(0,Math.min(minutes,snap.simulated_elapsed_minutes-started));
      rows.push({state:name,label:labels[name],start_minute:started,
        end_minute:started+duration, phase:i<snap.stage_index?"complete":snap.terminal?"complete":"current",
        simulation_only:true});
      started += minutes;
    }
    if(snap.state==="CANCELLED"){
      rows.push({state:"CANCELLED",label:labels.CANCELLED,
        start_minute:snap.simulated_elapsed_minutes,end_minute:snap.simulated_elapsed_minutes,
        phase:"stopped",simulation_only:true});
    }
    return rows;
  };
  function usage(){
    const all=snapshotList();
    return {tasks:all.length,completed:all.filter(t=>t.state==="COMPLETED").length,
      active:all.filter(t=>!t.terminal).length,
      simulated_elapsed_minutes:all.reduce((sum,t)=>sum+t.simulated_elapsed_minutes,0),
      real_calls:0,real_charges:0};
  }
  function stageUsage(){
    const names=["DIALING","IVR","HOLD","CONSULTING"];
    const stats=names.map(name=>({state:name,label:labels[name],
      simulated_minutes:0,simulated_visits:0}));
    for(const task of snapshotList())for(const stage of asTimeline(task)){
      const bucket=stats.find(s=>s.state===stage.state);
      if(bucket){bucket.simulated_minutes+=stage.end_minute-stage.start_minute;bucket.simulated_visits++}
    }
    return {simulation_only:true,stages:stats,real_calls:0,real_charges:0};
  }
  function createTask(body){
    if(!valid(body.goal,3,300)||!valid(body.destination,2,80))fail("전화 목적과 가상 대상을 확인해 주세요");
    if(!valid(body.request_id,8,80)||!stages[body.scenario]||!["web","claw"].includes(body.source))fail("요청 형식이 올바르지 않습니다");
    if(byRequest.has(body.request_id))return makeSnapshot(tasks.get(byRequest.get(body.request_id)));
    if(tasks.size>=50)fail("체험 작업 수 한도에 도달했습니다. 페이지를 다시 열어주세요");
    let notes="",questions="";
    if(body.script_id){
      const script=getScript(body.script_id);
      if(script.goal!==body.goal||script.destination!==body.destination)fail("대본의 내용이 변경되었습니다");
      notes=script.notes;questions=script.questions;
    }
    const task={id:taskId(),request_id:body.request_id,started:now(),
      created_at:new Date().toISOString(),source:body.source,goal:body.goal,
      destination:body.destination,scenario:body.scenario,
      script_id:body.script_id||null,notes,questions, frozen:null};
    tasks.set(task.id,task); byRequest.set(task.request_id,task.id);
    return makeSnapshot(task);
  }
  const validateScript = raw=>{
    for(const [name,min,max] of [["title",2,80],["destination",2,80],["goal",3,300],["questions",0,400],["notes",0,400]]){
      const value=raw[name]??"";
      if(!valid(value,min,max))fail("대본의 "+name+" 항목을 확인해 주세요");
    }
    return Object.fromEntries(["title","destination","goal","questions","notes"].map(k=>[k,raw[k]?.trim()||""]));
  };
  function editScript(path,init){
    const id=decodeURIComponent(path.split("/").pop());
    const body=parseBody(init);
    const pos=scripts.findIndex(s=>s.script_id===id);
    if(pos<builtIn)fail("예시 대본은 수정하거나 삭제할 수 없습니다");
    const old=getScript(id);
    if(!Number.isInteger(body.revision)||body.revision!==old.revision)fail("대본의 수정 버전이 일치하지 않습니다");
    if(init.method==="DELETE"){scripts.splice(pos,1);return {deleted:true,script_id:id}}
    const updated={...validateScript(body),script_id:id,revision:old.revision+1,built_in:false};
    scripts[pos]=updated;return {...updated};
  }
  window.publicDemoApi=async (path,init={})=>{
    const method=init.method||"GET";
    // All operations are synchronous in browser memory; no fetch, XHR,
    // WebSocket, localStorage, sessionStorage or cloud API is ever used.
    if(path==="/api/usage"&&method==="GET")return usage();
    if(path==="/api/usage/stages"&&method==="GET")return stageUsage();
    if(path==="/api/scripts"&&method==="GET")return {scripts:scripts.map(s=>({...s}))};
    if(path==="/api/scripts"&&method==="POST"){
      if(scripts.length>=43)fail("최대 40개의 개인 대본을 시연할 수 있습니다");
      const script={...validateScript(parseBody(init)),script_id:"custom-"+taskId(),revision:1,built_in:false};
      scripts.push(script);return {...script};
    }
    if(path.startsWith("/api/scripts/")&&["PUT","DELETE"].includes(method))return editScript(path,init);
    if(path==="/api/tasks"&&method==="GET")return {tasks:snapshotList()};
    if(path==="/api/tasks"&&method==="POST")return createTask(parseBody(init));
    const parts=path.split("/").filter(Boolean);
    if(parts.length>=3&&parts[0]==="api"&&parts[1]==="tasks"){
      const task=tasks.get(parts[2])||fail("모의 작업을 찾지 못했습니다");
      if(parts.length===3&&method==="GET")return makeSnapshot(task);
      if(parts.length===4&&parts[3]==="cancel"&&method==="POST"){
        const snap=makeSnapshot(task);
        if(!snap.terminal)task.frozen={...snap,state:"CANCELLED",terminal:true,
          result:"모의 작업이 중지되었습니다. 실제 발신은 없었습니다."};
        return makeSnapshot(task);
      }
      if(parts.length===4&&parts[3]==="timeline"&&method==="GET")return {timeline:asTimeline(makeSnapshot(task))};
    }
    return fail("지원하지 않는 데모 요청입니다");
  };
  window.publicDemoReport = taskId => {
    const snap=makeSnapshot(tasks.get(taskId)||fail("모의 작업이 없습니다"));
    const rows=[
      "PADIEM Phone — 공개 데모 보고서",
      "※ 실제 발신·ARS·상담·AI 음성·녹음이 전혀 없는 시뮬레이션입니다.",
      "", "모의 작업 ID: "+snap.task_id,
      "대상(가상): "+snap.destination,"업무 목표: "+snap.goal,
      "확인할 질문: "+(snap.questions||"(없음)"),
      "주의사항: "+(snap.notes||"(없음)"),
      "모의 상태: "+(labels[snap.state]||snap.state),
      "가상 경과시간: "+snap.simulated_elapsed_minutes+"분",
      "실제 전화 발신: 0건", "실제 요금: 0원",
      "", "모의 진행 기록:" ];
    for(const row of asTimeline(snap))rows.push("- "+row.label+" (가상 "+row.start_minute+"–"+row.end_minute+"분)");
    rows.push("", "결과: "+(snap.result||"모의 진행 중"),"","실제 고객센터 상담 결과나 결제 영수증이 아닙니다.");
    return rows.join("\n")+"\n";
  };
})();
