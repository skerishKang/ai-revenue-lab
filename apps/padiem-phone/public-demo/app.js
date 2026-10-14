"use strict";

// Public demo — all UI state and scripts are in browser memory only.
// No account connection, persistent storage, outbound telephony or billing.
const $ = id => document.getElementById(id);
let templates = [];
let selectedScript = null;
let editingScript = null;
const stateLabels = {
  DIALING: "전화 연결 시도", IVR: "ARS 메뉴 진행",
  HOLD: "상담원 연결 대기", CONSULTING: "상담 진행",
  COMPLETED: "모의 완료", NO_ANSWER: "응답 없음",
  AUTH_REQUIRED: "본인확인 필요", CANCELLED: "중단", INTERRUPTED: "미리보기 재시작으로 중단",
};
let activeId = null;
let pollTimer = null;
let refreshSerial = 0;

const setText = (id, value) => { $(id).textContent = String(value); };
const button = (label, className, action) => {
  const el = document.createElement("button");
  el.type = "button";
  el.className = className;
  el.textContent = label;
  el.addEventListener("click", action);
  return el;
};
const textNode = (tag, value, className) => {
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.textContent = value;
  return el;
};

async function api(path, init = {}) {
  return window.publicDemoApi(path, init);
}

function showPage(name) {
  if (!$ (name) || !$ (name).classList.contains("page")) return;
  document.querySelectorAll(".page").forEach(el => el.classList.toggle("active", el.id === name));
  document.querySelectorAll("[data-page]").forEach(el => {
    if (el.classList.contains("nav-link")) el.classList.toggle("active", el.dataset.page === name);
  });
  setText("breadcrumb", ({ dashboard: "대시보드", scripts: "전화 대본", history: "통화 기록", usage: "사용량" })[name]);
  if (name === "history") refreshHistory();
  if (name === "usage") refreshUsage();
  if (name === "scripts") refreshScripts();
}

function applyTemplate(t) {
  $("destination").value = t.destination;
  $("goal").value = t.goal;
  selectedScript = t;
  showPage("dashboard");
  $("goal").focus();
}

function makeTemplate(t, full) {
  const wrap = document.createElement("div");
  if (!full) {
    wrap.className = "script-row";
    const details = document.createElement("div");
    details.append(textNode("strong", t.title), textNode("small", t.questions || t.goal));
    wrap.append(details, button("사용", "small-button", () => applyTemplate(t)));
  } else {
    wrap.className = "template-card";
    wrap.append(
      textNode("div", t.built_in ? "◫" : "✦", "template-icon"),
      textNode("h2", t.title),
      textNode("p", t.questions || t.goal),
      button("이 대본으로 시작 ↗", "small-button", () => applyTemplate(t)),
    );
    if (!t.built_in) {
      wrap.append(button("편집", "small-button edit-script", () => openScriptEditor(t)));
    }
  }
  return wrap;
}
async function refreshScripts() {
  try {
    const response = await api("/api/scripts");
    templates = response.scripts;
    $("quickTemplates").replaceChildren(...templates.slice(0, 3).map(t => makeTemplate(t, false)));
    $("scriptsGrid").replaceChildren(...templates.map(t => makeTemplate(t, true)));
    setText("scriptMessage", "");
  } catch (err) {
    setText("scriptMessage", "대본 목록 조회 실패: " + err.message);
  }
}

function openScriptEditor(t = null) {
  editingScript = t;
  setText("scriptEditorTitle", t ? "대본 수정" : "나만의 대본 만들기");
  for (const [id, key] of [
    ["scriptTitle", "title"], ["scriptDestination", "destination"], ["scriptGoal", "goal"],
    ["scriptQuestions", "questions"], ["scriptNotes", "notes"]
  ]) $(id).value = t ? t[key] : "";
  $("deleteScriptButton").hidden = !t;
  $("scriptEditor").hidden = false;
  setText("scriptMessage", "");
  $("scriptTitle").focus();
}

function closeScriptEditor() {
  editingScript = null;
  $("scriptEditor").hidden = true;
  setText("scriptMessage", "");
}

$("newScriptButton").addEventListener("click", () => openScriptEditor());
$("scriptCancelButton").addEventListener("click", closeScriptEditor);
$("scriptEditor").addEventListener("submit", async event => {
  event.preventDefault();
  const b = $("saveScriptButton");
  b.disabled = true;
  setText("scriptMessage", "");
  const raw = {
    title: $("scriptTitle").value, destination: $("scriptDestination").value,
    goal: $("scriptGoal").value, questions: $("scriptQuestions").value,
    notes: $("scriptNotes").value,
  };
  const saved = editingScript;
  if (saved) raw.revision = saved.revision;
  try {
    await api(saved ? "/api/scripts/" + saved.script_id : "/api/scripts", {
      method: saved ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(raw),
    });
    if (selectedScript?.script_id === saved?.script_id) selectedScript = null;
    closeScriptEditor();
    await refreshScripts();
  } catch (err) {
    setText("scriptMessage", "대본 저장 실패: " + err.message);
  } finally { b.disabled = false; }
});
$("deleteScriptButton").addEventListener("click", async () => {
  const saved = editingScript;
  if (!saved || saved.built_in) return;
  // Deletion changes only the local mock script; historical tasks remain immutable.
  if (!window.confirm("선택한 대본을 삭제할까요? 모의 작업 기록은 유지됩니다.")) return;
  try {
    await api("/api/scripts/" + saved.script_id, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({revision: saved.revision}),
    });
    if (selectedScript?.script_id === saved.script_id) selectedScript = null;
    closeScriptEditor();
    await refreshScripts();
  } catch (err) {
    setText("scriptMessage", "대본 삭제 실패: " + err.message);
  }
});
$("goal").addEventListener("input", () => { selectedScript = null; });
$("destination").addEventListener("input", () => { selectedScript = null; });

async function refreshSummary() {
  try {
    const usage = await api("/api/usage");
    setText("statTotal", usage.tasks);
    setText("statCompleted", usage.completed);
    setText("statActive", usage.active);
    $("statMinutes").replaceChildren(document.createTextNode(String(usage.simulated_elapsed_minutes) + " "), textNode("em", "분"));
    setText("usageTotal", usage.tasks);
    setText("usageCompleted", usage.completed);
    $("usageMinutes").replaceChildren(document.createTextNode(String(usage.simulated_elapsed_minutes) + " "), textNode("em", "분"));
  } catch (err) {
    setText("formMessage", "서버에 연결할 수 없습니다: " + err.message);
  }
}
async function refreshHistory() {
  try {
    const data = await api("/api/tasks");
    const tbody = $("historyBody");
    tbody.replaceChildren();
    if (!data.tasks.length) {
      const tr = document.createElement("tr"), td = document.createElement("td");
      td.colSpan = 5;
      td.textContent = "아직 모의 전화 업무 기록이 없습니다.";
      tr.append(td); tbody.append(tr); return;
    }
    data.tasks.forEach(task => {
      const tr = document.createElement("tr");
      const taskLink = document.createElement("td");
      taskLink.append(button(task.task_id.slice(0, 8) + " ↗", "detail-link",
        () => showHistoryDetails(task.task_id)));
      const status = textNode("span", stateLabels[task.state] || task.state, "state-pill " +
        (task.state === "NO_ANSWER" || task.state === "CANCELLED" || task.state === "INTERRUPTED" ? "fail" : task.terminal ? "" : "progress"));
      const cells = [
        taskLink,
        textNode("td", task.destination),
        document.createElement("td"),
        textNode("td", task.simulated_elapsed_minutes + "분"),
        textNode("td", task.source === "claw" ? "Claw (가상)" : "전용 페이지"),
      ];
      cells[2].append(status);
      cells.forEach(c => tr.append(c));
      tbody.append(tr);
    });
  } catch (err) {
    const td = document.createElement("td"); td.colSpan = 5; td.textContent = err.message;
    const tr = document.createElement("tr"); tr.append(td);
    $("historyBody").replaceChildren(tr);
  }
}
function appendTimeline(root, events) {
  const timeline = document.createElement("ol");
  timeline.className = "phone-stage-timeline";
  for (const event of events) {
    const entry = document.createElement("li");
    entry.className = "phone-stage " + event.phase;
    entry.append(
      textNode("strong", event.label),
      textNode("span", "가상 " + event.start_minute + "–" + event.end_minute + "분"),
    );
    timeline.append(entry);
  }
  root.append(timeline);
}
async function downloadTaskReport(taskId) {
  try {
    const report = window.publicDemoReport(taskId);
    const blob = new Blob(["\uFEFF", report], {type:"text/plain;charset=utf-8"});
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = "padiem-phone-mock-" + taskId.slice(0, 12) + ".txt";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1200);
  } catch (error) {
    const node = $("reportMessage");
    if (node) node.textContent = "보고서 다운로드 실패: " + error.message;
  }
}
async function showHistoryDetails(taskId) {
  const root = $("historyDetailsContent");
  const panel = $("historyDetails");
  try {
    const task = await api("/api/tasks/" + taskId);
    const stages = await api("/api/tasks/" + taskId + "/timeline");
    root.replaceChildren();
    const items = [
      ["대상 기관", task.destination],
      ["전화 목적", task.goal],
      ["반드시 확인할 질문", task.questions || "(없음)"],
      ["주의사항", task.notes || "(없음)"],
      ["상태", stateLabels[task.state] || task.state],
      ["가상 수행시간", task.simulated_elapsed_minutes + "분"],
      ["처리 결과", task.result || "모의 진행 중"],
    ];
    items.forEach(([title, value]) => {
      const part = document.createElement("div");
      part.className = "detail-item";
      part.append(textNode("strong", title), textNode("p", value));
      root.append(part);
    });
    const extra = document.createElement("div");
    extra.className = "history-extras";
    extra.append(textNode("strong", "모의 진행 단계"));
    appendTimeline(extra, stages.timeline);
    extra.append(
      button("모의 업무 보고서(.txt) 저장", "secondary report-download",
        () => downloadTaskReport(task.task_id)),
      textNode("p", "실제 전화 통화나 상담 녹취가 아닙니다.", "report-notice")
    );
    const message = textNode("p", "", "form-message");
    message.id = "reportMessage";
    extra.append(message);
    root.append(extra);
    panel.hidden = false;
    panel.scrollIntoView({behavior: "smooth", block: "nearest"});
  } catch (err) {
    root.replaceChildren(textNode("p", "기록 상세 조회 실패: " + err.message));
    panel.hidden = false;
  }
}
$("closeHistoryDetails").addEventListener("click", () => {
  $("historyDetails").hidden = true;
});
async function refreshUsage() {
  await refreshSummary();
  const root = $("usageStageBreakdown");
  try {
    const result = await api("/api/usage/stages");
    root.replaceChildren();
    const maximum = Math.max(1, ...result.stages.map(item => item.simulated_minutes));
    for (const stage of result.stages) {
      const row = document.createElement("div");
      row.className = "usage-stage-row";
      const heading = document.createElement("div");
      heading.className = "usage-stage-heading";
      heading.append(
        textNode("strong", stage.label),
        textNode("span", stage.simulated_minutes + "분 · " + stage.simulated_visits + "회 진입")
      );
      const track = document.createElement("div");
      track.className = "usage-stage-track";
      const fill = document.createElement("span");
      fill.style.width = Math.round(stage.simulated_minutes / maximum * 100) + "%";
      track.append(fill);
      row.append(heading, track);
      root.append(row);
    }
  } catch (error) {
    root.replaceChildren(textNode("p", "가상 사용량 조회 실패: " + error.message));
  }
}

function renderActive(task) {
  const root = $("activeTask");
  root.className = "";
  root.replaceChildren();
  root.append(textNode("p", task.goal, "task-title"));
  const status = document.createElement("div"); status.className = "task-status";
  status.append(textNode("strong", stateLabels[task.state] || task.state),
    textNode("span", task.terminal ? "종료" : "진행 중", "state-pill"));
  root.append(status);
  const bar = document.createElement("div"); bar.className = "progress-bar";
  const fill = document.createElement("span");
  fill.style.width = Math.round((task.stage_index + 1) / task.stage_total * 100) + "%";
  bar.append(fill); root.append(bar);
  const meta = document.createElement("div"); meta.className = "task-meta";
  meta.append(textNode("span", "가상 수행시간 " + task.simulated_elapsed_minutes + "분"),
    textNode("span", "실제 발신 0건"));
  root.append(meta);
  if (task.terminal) {
    root.append(textNode("div", task.result || "모의 작업 종료", "task-result"));
    root.append(button("모의 업무 보고서 저장", "small-button",
      () => downloadTaskReport(task.task_id)));
  } else {
    const actions = document.createElement("div"); actions.className = "task-actions";
    actions.append(button("작업 중단", "danger", cancelActive)); root.append(actions);
  }
}

async function tick() {
  if (!activeId) return;
  const sequence = ++refreshSerial;
  try {
    const task = await api("/api/tasks/" + activeId);
    if (sequence !== refreshSerial) return;
    renderActive(task);
    await refreshSummary();
    if (task.terminal) {
      clearInterval(pollTimer); pollTimer = null;
      $("createButton").disabled = false;
      await refreshHistory();
    }
  } catch (err) {
    clearInterval(pollTimer); pollTimer = null;
    $("createButton").disabled = false;
    setText("formMessage", err.message);
  }
}

async function cancelActive() {
  if (!activeId) return;
  try {
    const task = await api("/api/tasks/" + activeId + "/cancel", { method: "POST" });
    renderActive(task);
    clearInterval(pollTimer); pollTimer = null;
    $("createButton").disabled = false;
    refreshSummary();
    refreshHistory();
  } catch (err) { setText("formMessage", err.message); }
}

$("createForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (pollTimer) return;
  $("createButton").disabled = true;
  setText("formMessage", "");
  const request = {
    request_id: "phone_" + crypto.randomUUID().replaceAll("-", ""),
    source: $("source").value,
    destination: $("destination").value,
    goal: $("goal").value,
    scenario: $("scenario").value,
    ...(selectedScript ? {script_id: selectedScript.script_id} : {}),
  };
  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    activeId = task.task_id;
    renderActive(task);
    refreshSummary();
    pollTimer = setInterval(tick, 450);
  } catch (err) {
    $("createButton").disabled = false;
    setText("formMessage", err.message);
  }
});
document.querySelectorAll("[data-page]").forEach(b => b.addEventListener("click", () => showPage(b.dataset.page)));
$("refreshHistory").addEventListener("click", refreshHistory);
$("refreshUsage").addEventListener("click", refreshUsage);
async function restoreActiveOnLoad() {
  try {
    const data = await api("/api/tasks");
    if (activeId || pollTimer || !Array.isArray(data.tasks)) return;
    const resumed = data.tasks.find(task => task.terminal === false);
    if (!resumed) return;
    activeId = resumed.task_id;
    renderActive(resumed);
    $("createButton").disabled = true;
    pollTimer = setInterval(tick, 450);
  } catch {
    // The existing summary and history loaders display preview errors.
  }
}
refreshSummary();
refreshHistory();
refreshScripts();
restoreActiveOnLoad();
