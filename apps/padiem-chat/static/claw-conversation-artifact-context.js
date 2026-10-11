/* #3933 Hark WEB-FIRST: read-only previous-work context for the current
 * conversation. It resolves only the already-completed artifacts of the
 * owner's own conversation through the EXISTING owner-scoped
 * /artifact-followup index route and shows them so the user can identify the
 * previous XLSX work precisely. A resolved or hand-picked reference is a
 * locator only: no file bytes are read, no READ/WRITE grant is issued and a
 * NEW owner approval is required before any further file work. This module
 * never stores artifacts and never creates a second conversation authority.
 */
(() => {
  "use strict";
  const CONTRACT = "claw-conversation-artifact-followup.v1";
  const CHAT_ID = /^chat_[a-f0-9]{32}$/;
  const DOC_ID = /^doc_[a-f0-9]{32}$/;
  const HASH = /^[a-f0-9]{64}$/;
  const MAX_CHOICES = 31;

  // Display-only identifiers. Anything outside this bounded grammar is
  // refused instead of being rendered.
  function safeName(value) {
    return typeof value === "string" && value.length >= 1 && value.length <= 180
      && !/[\\/\r\n\x00]/.test(value);
  }

  function validateChoice(item) {
    return Boolean(item && typeof item === "object" && !Array.isArray(item)
      && DOC_ID.test(item.artifact_id) && safeName(item.filename)
      && Number.isSafeInteger(item.ordinal) && item.ordinal > 0
      && HASH.test(item.integrity_ref));
  }

  // A reference is never an authorization: the server must still report that
  // it issued no grant and loaded no source material.
  function validateFollowup(body) {
    const followup = body && typeof body === "object" ? body.followup : null;
    if (!body || body.ok !== true || !followup || typeof followup !== "object"
        || followup.contract_version !== CONTRACT
        || followup.read_grant_issued !== false
        || followup.source_material_loaded !== false
        || followup.provider_write_authorized !== false
        || followup.memory_restored !== false) return null;
    if (followup.status === "resolved") {
      if (!DOC_ID.test(followup.source_artifact_id)
          || !HASH.test(followup.source_integrity_ref)
          || typeof followup.source_run_ref !== "string"
          || !followup.source_run_ref) return null;
      if (followup.source_filename !== undefined
          && !safeName(followup.source_filename)) return null;
      return {
        status: "resolved",
        artifactId: followup.source_artifact_id,
        integrityRef: followup.source_integrity_ref,
        filename: followup.source_filename === undefined
          ? null : followup.source_filename,
      };
    }
    if (followup.status === "confirmation_required") {
      if (!Array.isArray(followup.choices)
          || followup.choices.length < 1
          || followup.choices.length > MAX_CHOICES
          || !followup.choices.every(validateChoice)
          || new Set(followup.choices.map((choice) => choice.artifact_id)).size
            !== followup.choices.length) return null;
      return {
        status: "confirmation_required",
        choices: followup.choices.map((choice) => ({
          artifactId: choice.artifact_id, filename: choice.filename,
          ordinal: choice.ordinal, integrityRef: choice.integrity_ref,
        })),
      };
    }
    if (followup.status === "not_available") return { status: "not_available" };
    return null;
  }

  async function requestFollowup(conversationId, params, fetchImpl) {
    const fetchFn = fetchImpl || (typeof fetch === "function" ? fetch : null);
    if (!fetchFn) throw new Error("artifact context transport unavailable");
    const query = new URLSearchParams({ kind: "xlsx", selector: params.selector });
    if (params.selector === "exact") {
      query.set("artifact_id", params.artifactId);
      query.set("integrity_ref", params.integrityRef);
    }
    // GET only, same-origin session, never a browser-supplied owner/workspace.
    const response = await fetchFn(
      "/api/claw/conversations/" + encodeURIComponent(conversationId)
        + "/artifact-followup?" + query.toString(),
      {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" },
      },
    );
    if (!response.ok) throw new Error("artifact context unavailable");
    return validateFollowup(await response.json().catch(() => null));
  }

  function init(host) {
    if (!host || typeof host.replaceChildren !== "function") return null;
    const doc = host.ownerDocument
      || (typeof document === "object" ? document : null);
    if (!doc || typeof doc.createElement !== "function") return null;
    // Accessible name lives in this Korean-only module, like the sibling web
    // XLSX panel; app.js must stay free of hardcoded Korean runtime copy.
    if (typeof host.setAttribute === "function") {
      host.setAttribute("aria-label", "이 대화의 완료된 작업 파일");
    }
    let token = 0;
    let state = { conversationId: null, status: "idle", options: 0 };

    const clear = () => {
      token += 1;
      state = { conversationId: null, status: "idle", options: 0 };
      host.hidden = true;
      host.replaceChildren();
    };

    const panelAction = () => {
      // Opening the EXISTING web Excel panel is the only follow-up action: it
      // starts no approval, reads no bytes and issues no grant by itself.
      const panel = typeof doc.getElementById === "function"
        ? doc.getElementById("clawWebOfficeDetails") : null;
      if (!panel) return null;
      const button = doc.createElement("button");
      button.type = "button";
      button.textContent = "새 승인 시작 (웹 Excel 패널 열기)";
      button.addEventListener("click", () => {
        panel.open = true;
        panel.scrollIntoView?.({ block: "start" });
        panel.querySelector?.("summary")?.focus?.();
      });
      return button;
    };

    const renderResolved = (context) => {
      host.replaceChildren();
      const title = doc.createElement("p");
      title.className = "claw-conversation-artifact-title";
      title.textContent = "이 대화의 완료된 XLSX 작업 결과";
      const detail = doc.createElement("p");
      detail.className = "claw-conversation-artifact-name";
      detail.textContent = context.filename
        ? "파일: " + context.filename
        : "완료된 XLSX 작업 파일 1개 (표시 이름 없음)";
      const note = doc.createElement("p");
      note.className = "claw-conversation-artifact-note";
      note.textContent = "확인된 참조일 뿐 파일 내용 권한이 아닙니다. "
        + "계속 수정하거나 새 버전을 만들려면 별도의 읽기·쓰기 승인이 필요합니다.";
      host.append(title, detail, note);
      const action = panelAction();
      if (action) host.append(action);
      host.hidden = false;
      state = {
        conversationId: state.conversationId, status: "resolved",
        options: 0, artifactId: context.artifactId,
      };
    };

    const renderChoices = (context) => {
      host.replaceChildren();
      const title = doc.createElement("p");
      title.className = "claw-conversation-artifact-title";
      title.textContent = "같은 이름의 완료된 XLSX 작업 파일이 여러 개 있습니다";
      const note = doc.createElement("p");
      note.className = "claw-conversation-artifact-note";
      note.textContent = "자동으로 추측하지 않습니다. 이어서 작업할 파일을 직접 선택하세요. "
        + "선택 후에도 새 승인이 필요합니다.";
      const list = doc.createElement("ul");
      list.className = "claw-conversation-artifact-choices";
      for (const choice of context.choices) {
        const item = doc.createElement("li");
        const button = doc.createElement("button");
        button.type = "button";
        button.textContent = choice.filename + " · 순번 " + choice.ordinal
          + " · 무결성 " + choice.integrityRef.slice(0, 12) + "…";
        button.addEventListener("click", () => void pick(choice, button));
        item.appendChild(button);
        list.appendChild(item);
      }
      host.append(title, note, list);
      host.hidden = false;
      state = {
        conversationId: state.conversationId, status: "confirmation_required",
        options: context.choices.length,
      };
    };

    async function pick(choice, button) {
      const conversationId = state.conversationId;
      if (!conversationId || state.status !== "confirmation_required") return;
      const current = token;
      button.disabled = true;
      try {
        // Re-confirm the EXACT owner-indexed identity before showing it; a
        // filename alone never selects a previous file.
        const context = await requestFollowup(conversationId, {
          selector: "exact", artifactId: choice.artifactId,
          integrityRef: choice.integrityRef,
        }, undefined);
        if (current !== token || conversationId !== state.conversationId) return;
        if (!context || context.status !== "resolved"
            || context.artifactId !== choice.artifactId
            || context.integrityRef !== choice.integrityRef
            || (context.filename !== null && context.filename !== choice.filename)) {
          throw new Error("exact artifact reference unavailable");
        }
        renderResolved(context);
      } catch (_error) {
        if (current !== token) return;
        button.disabled = false;
        state = {
          conversationId: conversationId,
          status: "confirmation_required", options: state.options,
        };
      }
    }

    function show(conversationId) {
      if (typeof conversationId !== "string" || !CHAT_ID.test(conversationId)) {
        clear();
        return Promise.resolve();
      }
      token += 1;
      const current = token;
      state = { conversationId, status: "loading", options: 0 };
      return requestFollowup(conversationId, { selector: "latest" })
        .then((context) => {
          if (current !== token || conversationId !== state.conversationId) return;
          if (!context || context.status === "not_available") {
            // No completed artifact in this conversation is an honest empty
            // state, never a guessed or remembered file.
            host.hidden = true;
            host.replaceChildren();
            state = { conversationId, status: "not_available", options: 0 };
            return;
          }
          if (context.status === "resolved") renderResolved(context);
          else renderChoices(context);
        })
        .catch(() => {
          if (current !== token) return;
          // Unavailable index/auth/network is not evidence of a file.
          host.hidden = true;
          host.replaceChildren();
          state = { conversationId, status: "unavailable", options: 0 };
        });
    }

    return {
      show, clear,
      getState: () => ({ ...state, hidden: host.hidden === true }),
    };
  }

  const api = Object.freeze({
    CONTRACT, safeName, validateChoice, validateFollowup, init,
  });
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window === "object") {
    window.PadiemClawConversationArtifactContext = api;
  }
})();
