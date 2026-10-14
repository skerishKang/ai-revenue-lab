"use strict";

// This browser app only speaks to the loopback mock API. No telephony SDK,
// payment provider, actual voice stream, or automatic outbound calling exists.
const $ = id => document.getElementById(id);
const templates = [
  { title: "일반 문의", icon: "◫", destination: "고객센터 (가상)", goal: "이용 내역을 확인하고 필요한 절차를 알려줘.", description: "이용 내역, 필요한 서류, 절차 등을 확인하는 기본 문의." },
  { title: "거래처 확인", icon: "▤", destination: "거래처 (가상)", goal: "현재 주문 건의 진행 상태와 예상 완료 시점을 확인해 줘.", description: "진행 상태와 일정 등 반복적으로 확인할 내용을 정리합니다." },
  { title: "예약 문의", icon: "▦", destination: "예약센터 (가상)", goal: "예약 가능한 시간과 필요한 준비 사항을 확인해 줘.", description: "예약 가능 여부, 시간, 준비 사항을 묻는 대본." },
];
const stateLabels = {
  DIALING: "전화 연결 시도", IVR: "ARS 메뉴 진행",
  HOLD: "상담원 연결 대기", CONSULTING: "상담 진행",
  COMPLETED: "모의 완료", NO_ANSWER: "응답 없음",
  AUTH_REQUIRED: "본인확인 필요", CANCELLED: "중단",
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
  const response = await fetch(path, { cache: "no-store", ...init });
  let body;
  try { body = await response.json(); }
  catch { throw new Error("응답을 확인할 수 없습니다."); }
  if (!response.ok) throw new Error(body.error || "작업 실패");
  return body;
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
}

function applyTemplate(t) {
  $("destination").value = t.destination;
  $("goal").value = t.goal;
  showPage("dashboard");
  $("goal").focus();
}

function makeTemplate(t, full) {
  const wrap = document.createElement("div");
  if (!full) {
    wrap.className = "script-row";
    const details = document.createElement("div");
    details.append(textNode("strong", t.title), textNode("small", t.description));
    wrap.append(details, button("사용", "small-button", () => applyTemplate(t)));
  } else {
    wrap.className = "template-card";
    wrap.append(
      textNode("div", t.icon, "template-icon"),
      textNode("h2", t.title),
      textNode("p", t.description),
      button("이 대본으로 시작 ↗", "small-button", () => applyTemplate(t)),
    );
  }
  return wrap;
}
templates.forEach(t => {
  $("quickTemplates").append(makeTemplate(t, false));
  $("scriptsGrid").append(makeTemplate(t, true));
});

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
      const status = textNode("span", stateLabels[task.state] || task.state, "state-pill " +
        (task.state === "NO_ANSWER" || task.state === "CANCELLED" ? "fail" : task.terminal ? "" : "progress"));
      const cells = [
        textNode("td", task.task_id.slice(0, 8)),
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
async function refreshUsage() { await refreshSummary(); }

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
refreshSummary();
refreshHistory();
