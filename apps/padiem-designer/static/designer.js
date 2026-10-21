/* PADIEM Designer preview client.
 *
 * The client owns three things: it asks the app for a turn, it puts the
 * returned generated UI into the sandboxed frame, and it carries the frame's
 * interaction state into the next turn.
 *
 * Everything lives inside one closure. A top-level `var history` would try to
 * assign the read-only `window.history` and would stop the whole script.
 */
"use strict";

(function () {
  var transcript = document.getElementById("transcript");
  var promptBox = document.getElementById("prompt");
  var generateButton = document.getElementById("generate");
  var clearButton = document.getElementById("clear");
  var frame = document.getElementById("frame");
  var stateBar = document.getElementById("state-bar");
  var statusBar = document.getElementById("status");
  var errorBar = document.getElementById("error");

  var turnHistory = [];
  var lastState = { values: {}, prompt: null };

function showError(message) {
  errorBar.textContent = message;
  errorBar.style.display = "block";
}

function clearError() {
  errorBar.textContent = "";
  errorBar.style.display = "none";
}

function appendTurn(who, body, context) {
  var turn = document.createElement("div");
  turn.className = "turn";
  var whoNode = document.createElement("div");
  whoNode.className = "who";
  whoNode.textContent = who;
  var bodyNode = document.createElement("div");
  bodyNode.className = "body";
  bodyNode.textContent = body || "";
  turn.appendChild(whoNode);
  turn.appendChild(bodyNode);
  if (context) {
    var ctxNode = document.createElement("div");
    ctxNode.className = "ctx";
    ctxNode.textContent = "전달한 UI 상태: " + context;
    turn.appendChild(ctxNode);
  }
  transcript.appendChild(turn);
  transcript.scrollTop = transcript.scrollHeight;
}

async function loadStatus() {
  try {
    var response = await fetch("/api/designer/health");
    var data = await response.json();
    var settings = data.settings || {};
    var route = data.route || {};
    var parts = [
      "경로=" + (route.kind || "?"),
      "툴호출=" + (route.supportsToolCalls ? "가능" : "불가"),
      "모델=" + (settings.modelId || "미설정"),
      "인증=" + (settings.authMode || "?"),
      "테넌트=" + (settings.tenantId || "미설정")
    ];
    statusBar.innerHTML = "";
    var strong = document.createElement("b");
    strong.textContent = parts.join(" · ");
    statusBar.appendChild(strong);
  } catch (error) {
    statusBar.textContent = "상태를 확인할 수 없습니다: " + error;
  }
}

async function renderUi(ui) {
  var response = await fetch("/api/designer/sandbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ui: ui })
  });
  if (!response.ok) {
    var payload = await response.json().catch(function () { return null; });
    throw new Error(
      payload && payload.error ? payload.error.message : "미리보기를 만들지 못했습니다."
    );
  }
  var documentText = await response.text();
  frame.srcdoc = documentText;
}

async function runTurn() {
  var prompt = promptBox.value.trim();
  if (!prompt) {
    showError("요청 내용을 입력하십시오.");
    return;
  }
  clearError();
  generateButton.disabled = true;
  appendTurn("요청", prompt, null);

  var body = { prompt: prompt, history: turnHistory, interaction_state: lastState };
  try {
    var response = await fetch("/api/designer/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    var data = await response.json();
    if (!response.ok || !data.ok) {
      var message = data && data.error ? data.error.message : "요청을 처리하지 못했습니다.";
      showError(message);
      appendTurn("오류", message, null);
      return;
    }
    turnHistory.push({ role: "user", content: prompt });
    if (data.text) {
      turnHistory.push({ role: "assistant", content: data.text });
    }
    var contextText = "";
    if (data.contextSent && Object.keys(data.contextSent.values || {}).length) {
      contextText = JSON.stringify(data.contextSent.values);
    }
    appendTurn(
      "AI (" + (data.modelId || "?") + ")",
      data.text || (data.ui ? "UI 를 생성했습니다." : ""),
      contextText
    );
    if (data.ui) {
      await renderUi(data.ui);
    }
  } catch (error) {
    showError(String(error));
  } finally {
    generateButton.disabled = false;
  }
}

window.addEventListener("message", function (event) {
  var data = event.data;
  if (!data || typeof data !== "object") {
    return;
  }
  if (data.type === "ui_state") {
    lastState = { values: data.values || {}, prompt: lastState.prompt };
    stateBar.textContent = "UI 상태: " + JSON.stringify(lastState.values);
  } else if (data.type === "prompt") {
    promptBox.value = String(data.text || "");
    appendTurn("UI", String(data.text || ""), null);
  } else if (data.type === "ui_ready") {
    stateBar.textContent = "UI 상태: " + JSON.stringify(lastState.values);
  }
});

generateButton.addEventListener("click", runTurn);
promptBox.addEventListener("keydown", function (event) {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    runTurn();
  }
});
clearButton.addEventListener("click", function () {
  turnHistory = [];
  lastState = { values: {}, prompt: null };
  transcript.innerHTML = "";
  stateBar.textContent = "UI 상태: (아직 없음)";
  frame.srcdoc = "";
});

  loadStatus();
})();
