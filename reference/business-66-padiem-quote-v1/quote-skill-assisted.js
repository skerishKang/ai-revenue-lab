/* B66 · Quote Beta — quote-skill-assisted.js
   견적서 관리 → 새 견적서 만들기 → 운영자에게 맡기기 (#3186 경로 C)

   흐름:
     고객 의뢰(기존 문의 API) → 회사 정보 기반 양식 후보(기존 후보 계약)
     → 운영자 승인(기존 승인 큐) → 계정 배정(기존 #3301 store)

   정직한 범위:
   - 고객은 승인 권한을 얻지 않는다. 후보는 고객 세션으로 접수되고, 승인·배정은
     권한 있는 운영자가 기존 승인 경로에서만 수행한다.
   - 후보에는 고객이 확인한 회사 정보와 기본값만 들어간다. 요청 메모는 운영자
     문의에만 남고 견적 기본 비고로 저장하지 않는다.
   - 파일을 선택하면 기존 추출 seam 을 재사용한다. 자동 분석이 꺼져 있으면
     실패를 그대로 표시하고 회사 정보만으로 후보를 준비한다.
   - 운영자가 고객 계정 대신 후보를 새로 작성하는 기능은 기존 경로에 없다.
     후보가 준비되지 않으면 문의만 접수되며, 화면은 그 사실을 숨기지 않는다.

   (DOM API만 사용 · innerHTML 미사용 · Node 스텁 DOM 으로 테스트) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-skill-auto.js"),
      require("./quote-skill-manual.js"),
      require("./file-intake.js")
    );
  } else {
    root.B66QuoteSkillAssisted = factory(
      root.B66QuoteSkillAuto,
      root.SavedQuoteSkillManual,
      root.B66FileIntake
    );
  }
})(typeof self !== "undefined" ? self : this, function (Auto, Manual, FileIntake) {
  "use strict";

  if (!Auto) throw new Error("B66QuoteSkillAuto is required");
  if (!Manual) throw new Error("SavedQuoteSkillManual is required");
  if (!FileIntake) throw new Error("B66FileIntake is required");

  var INQUIRY_ENDPOINT = "/api/padiem/b66/inquiries";
  var CATEGORY = "quote_skill_assist";
  var INQUIRY_ID_PATTERN = /^b66inq_[0-9a-f]{32}$/;
  var CONTROL_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

  var DIALOG_ID = "skillAssistDialog";
  var TITLE_ID = "skillAssistTitle";
  var STATUS_ID = "skillAssistStatus";
  var BODY_ID = "skillAssistBody";
  var FILE_INPUT_ID = "skassist-file";

  var LIMITS = Object.freeze({
    company: 120,
    name: Manual.LIMITS.name,
    phone: 40,
    email: 160,
    note: 1000,
    subject: 120,
    body: 3000
  });

  var MESSAGES = {
    auth_required: "운영자에게 맡기기는 로그인한 계정에서만 사용할 수 있습니다.",
    invalid_company: "회사명을 입력해 주세요.",
    invalid_name: "내 견적서 이름을 확인해 주세요.",
    inquiry_transport_unavailable: "의뢰 접수 기능을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    inquiry_request_failed: "의뢰를 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    inquiry_response_invalid: "의뢰 접수 결과를 확인하지 못했습니다.",
    inquiry_unauthorized: "로그인이 만료되었습니다. 다시 로그인한 뒤 요청해 주세요.",
    inquiry_rate_limited: "의뢰는 한 시간에 3건까지 접수할 수 있습니다.",
    inquiry_unavailable: "의뢰 접수 기능을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    invalid_inquiry: "의뢰 내용을 확인해 주세요.",
    inquiry_too_large: "의뢰 내용이 너무 큽니다. 요청 내용을 줄여 주세요.",
    candidate_unavailable: "양식 후보를 준비하지 못했지만 의뢰는 접수되었습니다. 운영자가 확인합니다.",
    pending: "양식 후보가 승인 대기로 접수되었습니다. 운영자 승인 후 이 계정의 내 견적서로 배정됩니다."
  };

  var SERVER_STATUS = Manual.SERVER_STATUS;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function h(doc, tag, attrs, children) {
    var node = doc.createElement(tag);
    var safe = attrs || {};
    Object.keys(safe).forEach(function (key) {
      if (key === "text") node.textContent = String(safe[key]);
      else if (key === "hidden") node.hidden = Boolean(safe[key]);
      else if (key === "htmlFor") node.setAttribute("for", String(safe[key]));
      else if (key === "checked" || key === "disabled" || key === "selected") {
        node[key] = Boolean(safe[key]);
        if (safe[key]) node.setAttribute(key, "");
      } else if (key === "value") node.value = String(safe[key]);
      else node.setAttribute(key, String(safe[key]));
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? doc.createTextNode(child) : child);
    });
    return node;
  }

  function dl(doc, rows) {
    var list = h(doc, "dl", { class: "skill-review-list" }, []);
    rows.forEach(function (row) {
      list.appendChild(h(doc, "dt", { text: row[0] }, []));
      list.appendChild(h(doc, "dd", { text: String(row[1]) }, []));
    });
    return list;
  }

  function note(doc, text) {
    return h(doc, "p", { class: "template-manage-note", text: text }, []);
  }

  function actionButton(doc, action, label, kind) {
    return h(doc, "button", {
      type: "button",
      class: "btn" + (kind ? " " + kind : ""),
      "data-action": action,
      text: label
    }, []);
  }

  function textInput(doc, id, value, extra) {
    var attrs = { id: id, value: value === null || value === undefined ? "" : value };
    if (extra) Object.keys(extra).forEach(function (key) { attrs[key] = extra[key]; });
    return h(doc, "input", attrs, []);
  }

  /* ── 순수 의뢰 계약 ── */

  function normalizeRequest(raw) {
    if (!isPlainObject(raw)) return { ok: false, code: "invalid_company" };
    var company = Manual.sanitizeText(raw.company, LIMITS.company, false);
    if (!company) return { ok: false, code: "invalid_company" };
    var name = Manual.sanitizeText(raw.name, LIMITS.name, false) || (company + " 견적서");
    if (!name) return { ok: false, code: "invalid_name" };
    return {
      ok: true,
      request: {
        name: name,
        company: company,
        phone: Manual.sanitizeText(raw.phone, LIMITS.phone, false),
        email: Manual.sanitizeText(raw.email, LIMITS.email, false),
        note: Manual.sanitizeText(raw.note, LIMITS.note, true)
      }
    };
  }

  function draftFor(request, profile) {
    var base = Auto.draftFromProfile(profile);
    return {
      name: request.name || base.name,
      sender: {
        company: request.company,
        rep: base.sender.rep,
        bizNo: base.sender.bizNo,
        address: base.sender.address,
        phone: request.phone || base.sender.phone,
        email: request.email || base.sender.email
      },
      validDays: base.validDays,
      taxMode: base.taxMode,
      memo: "",
      variableFlags: { memo: true, taxMode: true }
    };
  }

  function analysisLabel(analysis) {
    if (analysis && analysis.ok) return "자동 분석 완료";
    if (analysis && analysis.code) return "자동 분석 사용 불가 (" + analysis.code + ")";
    return "선택 안 함";
  }

  function buildInquiryPayload(request, candidateResult, fileMeta, analysis) {
    var outcome = isPlainObject(candidateResult) ? candidateResult : {};
    var noteText = typeof request.note === "string" ? request.note : "";
    if (noteText.length > LIMITS.note) noteText = noteText.slice(0, LIMITS.note);
    var lines = [
      "[견적서 양식 의뢰]",
      "회사명: " + request.company
    ];
    var contact = [request.phone, request.email].filter(function (value) { return value; });
    if (contact.length) lines.push("담당 연락처: " + contact.join(" / "));
    lines.push("요청 내용: " + (noteText || "(없음)"));
    lines.push("파일: " + (fileMeta ? fileMeta.name + " (" + analysisLabel(analysis) + ")" : "선택 안 함"));
    if (outcome.ok === true && typeof outcome.candidateId === "string" && outcome.candidateId) {
      lines.push("양식 후보: " + outcome.candidateId + " (상태: " + (outcome.status || "pending") + ")");
      lines.push("처리: 관리자 승인 요청에서 후보를 검토해 주세요.");
    } else {
      lines.push("양식 후보: 준비 실패 (" + (outcome.code || "candidate_unavailable") + ")");
      lines.push("처리: 고객 계정에 후보가 없습니다. 고객에게 다시 요청해 주세요.");
    }
    var subject = ("[견적서 양식 의뢰] " + request.company).slice(0, LIMITS.subject);
    var body = lines.join("\n").slice(0, LIMITS.body);
    if (CONTROL_RE.test(subject) || CONTROL_RE.test(body)) {
      return { ok: false, code: "invalid_inquiry" };
    }
    return {
      ok: true,
      payload: { category: CATEGORY, subject: subject, body: body }
    };
  }

  function transportFromFetch(fetchFn) {
    if (typeof fetchFn !== "function") return null;
    return function (request) {
      return Promise.resolve()
        .then(function () {
          return fetchFn(request.url, {
            method: request.method,
            cache: "no-store",
            credentials: "same-origin",
            headers: Object.assign({ "Accept": "application/json" }, request.headers || {}),
            body: request.body === null || request.body === undefined
              ? undefined
              : JSON.stringify(request.body)
          });
        })
        .then(function (response) {
          var status = response && typeof response.status === "number" ? response.status : 0;
          var ok = Boolean(response && response.ok);
          var parsed = response && typeof response.json === "function"
            ? Promise.resolve(response.json()).catch(function () { return null; })
            : Promise.resolve(null);
          return parsed.then(function (data) {
            return { status: status, ok: ok, data: data };
          });
        });
    };
  }

  function transportFor(options) {
    if (typeof options.transport === "function") return options.transport;
    return transportFromFetch(options.fetch);
  }

  function failInquiry(code) {
    return {
      ok: false,
      inquiryId: "",
      code: code,
      message: MESSAGES[code] || MESSAGES.inquiry_request_failed
    };
  }

  function submitInquiry(payload, options) {
    var opts = options || {};
    var transport = transportFor(opts);
    if (!transport) return Promise.resolve(failInquiry("inquiry_transport_unavailable"));
    return Promise.resolve()
      .then(function () {
        return transport({
          method: "POST",
          url: INQUIRY_ENDPOINT,
          headers: { "Content-Type": "application/json" },
          body: payload
        });
      })
      .then(function (response) {
        var status = response && typeof response.status === "number" ? response.status : 0;
        var data = response && isPlainObject(response.data) ? response.data : null;
        if (status === 401 || status === 403) return failInquiry("inquiry_unauthorized");
        if (status === 429) return failInquiry("inquiry_rate_limited");
        if (status === 413) return failInquiry("inquiry_too_large");
        if (status === 400) return failInquiry("invalid_inquiry");
        if (status === 503) return failInquiry("inquiry_unavailable");
        if (!response || response.ok !== true || !data || data.ok !== true) {
          var code = data && isPlainObject(data.error) && typeof data.error.code === "string"
            ? data.error.code
            : "inquiry_request_failed";
          return failInquiry(MESSAGES[code] ? code : "inquiry_request_failed");
        }
        if (typeof data.inquiry_id !== "string" || !INQUIRY_ID_PATTERN.test(data.inquiry_id)) {
          return failInquiry("inquiry_response_invalid");
        }
        return { ok: true, inquiryId: data.inquiry_id, code: "", message: "" };
      })
      .catch(function () { return failInquiry("inquiry_request_failed"); });
  }

  function candidateOutcome(result) {
    if (!result || result.ok !== true) {
      return {
        ok: false,
        candidateId: "",
        status: null,
        code: result && result.code ? result.code : "candidate_unavailable"
      };
    }
    return {
      ok: true,
      candidateId: result.candidateId,
      status: result.status,
      code: ""
    };
  }

  /* 의뢰는 후보 준비 실패와 무관하게 접수한다. 실패 사실은 문의 본문에 남는다. */
  function run(request, options) {
    var opts = options || {};
    var normalized = normalizeRequest(request);
    if (!normalized.ok) {
      return Promise.resolve({
        ok: false,
        request: null,
        requestCode: normalized.code,
        candidate: candidateOutcome(null),
        inquiry: failInquiry("invalid_inquiry"),
        payload: null
      });
    }
    request = normalized.request;
    var built = Auto.buildCandidate(draftFor(request, opts.companyProfile), {
      extraction: opts.extraction,
      fileMeta: opts.fileMeta,
      now: opts.now
    });
    var submitted = built.ok
      ? Auto.submitCandidate(built.candidate, opts)
      : Promise.resolve({ ok: false, code: built.code || "candidate_unavailable" });
    return submitted.then(candidateOutcome).then(function (result) {
      var inquiry = buildInquiryPayload(request, result, opts.fileMeta, opts.analysis);
      if (!inquiry.ok) {
        return {
          ok: false,
          request: request,
          candidate: result,
          inquiry: failInquiry(inquiry.code),
          payload: null
        };
      }
      return submitInquiry(inquiry.payload, opts).then(function (sent) {
        return {
          ok: sent.ok,
          request: request,
          candidate: result,
          inquiry: sent,
          payload: inquiry.payload
        };
      });
    }).catch(function () {
      return {
        ok: false,
        request: request,
        candidate: candidateOutcome(null),
        inquiry: failInquiry("inquiry_request_failed"),
        payload: null
      };
    });
  }

  /* ── DOM 컨트롤러 ── */

  var dialog = null;
  var state = null;

  function signedIn(env) {
    var source = typeof env.authState === "function" ? env.authState() : env.authState;
    if (!isPlainObject(source)) return false;
    return source.authenticated === true && source.privateStateReadable === true;
  }

  function profileOf(env) {
    if (typeof env.companyProfile === "function") return env.companyProfile();
    return env.companyProfile;
  }

  function notify(message) {
    var node = dialog ? dialog.querySelector("#" + STATUS_ID) : null;
    if (node) node.textContent = message || "";
  }

  function ensureDialog(doc) {
    if (dialog && dialog.ownerDocument === doc) return dialog;
    var existing = doc.getElementById(DIALOG_ID);
    if (existing) {
      dialog = existing;
      return dialog;
    }
    dialog = doc.createElement("dialog");
    dialog.id = DIALOG_ID;
    dialog.className = "b66-skill-start-dialog b66-skill-assist-dialog";
    dialog.setAttribute("aria-labelledby", TITLE_ID);
    var heading = h(doc, "div", { class: "b66-skill-start-heading" }, []);
    heading.appendChild(h(doc, "h2", { id: TITLE_ID, text: "운영자에게 양식 만들기 맡기기" }, []));
    var close = h(doc, "button", { type: "button", text: "닫기" }, []);
    close.setAttribute("aria-label", "양식 의뢰 닫기");
    close.addEventListener("click", function () {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.hidden = true;
    });
    heading.appendChild(close);
    dialog.appendChild(heading);
    dialog.appendChild(note(doc,
      "회사 정보와 요청만 남기면 양식 후보가 승인 대기로 접수됩니다. " +
      "권한 있는 운영자가 검토한 뒤 승인해야 이 계정의 내 견적서로 배정됩니다."));
    dialog.appendChild(h(doc, "p", { id: STATUS_ID, class: "template-manage-note", text: "" }, []));
    dialog.appendChild(h(doc, "div", { id: BODY_ID }, []));
    dialog.addEventListener("click", function (event) {
      var target = event.target;
      var action = target && typeof target.closest === "function"
        ? target.closest("[data-action]")
        : null;
      if (!action || !state) return;
      handleAction(action.getAttribute("data-action"));
    });
    dialog.addEventListener("close", function () { state = null; });
    doc.body.appendChild(dialog);
    return dialog;
  }

  function render() {
    if (!dialog || !state) return;
    var doc = dialog.ownerDocument;
    var body = dialog.querySelector("#" + BODY_ID);
    clear(body);
    if (!state.signedIn) {
      body.appendChild(note(doc,
        "운영자에게 맡기기는 로그인한 계정에서만 사용할 수 있습니다. " +
        "로그인하면 회사 정보를 확인해 양식 후보를 승인 요청으로 접수할 수 있습니다."));
      body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "skassist-signin", "로그인", "primary")
      ]));
      notify(MESSAGES.auth_required);
      return;
    }
    if (state.result) { renderResult(doc, body); return; }
    renderForm(doc, body);
  }

  function renderForm(doc, body) {
    var entry = state.draft;
    var form = h(doc, "div", { class: "fields" }, []);
    var nameLabel = h(doc, "label", { htmlFor: "skassist-name" }, ["내 견적서 이름 "]);
    nameLabel.appendChild(textInput(doc, "skassist-name", entry.name, { maxlength: String(LIMITS.name) }));
    form.appendChild(nameLabel);
    var companyLabel = h(doc, "label", { htmlFor: "skassist-company" }, ["회사명 "]);
    companyLabel.appendChild(textInput(doc, "skassist-company", entry.sender.company,
      { maxlength: String(LIMITS.company), required: "required" }));
    form.appendChild(companyLabel);
    var phoneLabel = h(doc, "label", { htmlFor: "skassist-phone" }, ["연락처 "]);
    phoneLabel.appendChild(textInput(doc, "skassist-phone", entry.sender.phone,
      { maxlength: String(LIMITS.phone), inputmode: "tel" }));
    form.appendChild(phoneLabel);
    var emailLabel = h(doc, "label", { htmlFor: "skassist-email" }, ["이메일 "]);
    emailLabel.appendChild(textInput(doc, "skassist-email", entry.sender.email, { maxlength: String(LIMITS.email) }));
    form.appendChild(emailLabel);
    body.appendChild(form);
    var noteLabel = h(doc, "label", { htmlFor: "skassist-note" }, ["요청 내용 "]);
    noteLabel.appendChild(h(doc, "textarea", { id: "skassist-note", value: "" }, []));
    body.appendChild(h(doc, "div", { class: "fields" }, [noteLabel]));
    body.appendChild(note(doc,
      "요청 내용은 운영자 문의에만 전달되며 견적 기본 비고로 저장되지 않습니다."));

    var fileRow = h(doc, "div", { class: "fields" }, []);
    fileRow.appendChild(dl(doc, [
      ["참고 파일", state.meta ? state.meta.name + " (" + state.meta.displaySize + ")" : "선택 안 함"],
      ["파일 자동 분석", analysisLabel(state.analysis)]
    ]));
    body.appendChild(fileRow);
    var input = h(doc, "input", {
      id: FILE_INPUT_ID,
      type: "file",
      accept: ".pdf,.docx,.pptx,.xlsx,.hwp,.hwpx,.jpg,.jpeg,.png,.webp",
      hidden: true
    }, []);
    input.addEventListener("change", onFileChosen);
    body.appendChild(input);
    var buttons = [
      actionButton(doc, "skassist-choose", state.meta ? "다른 파일 선택" : "참고 파일 선택", "soft"),
      actionButton(doc, "skassist-submit", state.busy ? "접수 중" : "의뢰 접수", "primary")
    ];
    body.appendChild(h(doc, "div", { class: "button-row" }, buttons));
    if (!state.busy) {
      notify(state.analysis && state.analysis.code
        ? Auto.analysisFailureMessage(state.analysis.code)
        : "회사 정보를 확인한 뒤 의뢰를 접수해 주세요.");
    }
  }

  function renderResult(doc, body) {
    var result = state.result;
    var rows = [];
    if (result.inquiry.ok) rows.push(["의뢰번호", result.inquiry.inquiryId]);
    else rows.push(["의뢰 접수", "실패 (" + result.inquiry.code + ")"]);
    if (result.candidate.ok) {
      rows.push(["양식 후보", result.candidate.candidateId]);
      rows.push(["후보 상태", result.candidate.status === "pending" ? "승인 대기 · 아직 사용할 수 없음"
        : result.candidate.status]);
    } else {
      rows.push(["양식 후보", "준비 실패 (" + result.candidate.code + ")"]);
    }
    body.appendChild(dl(doc, rows));
    if (result.inquiry.ok && result.candidate.ok && result.candidate.status === SERVER_STATUS.PENDING) {
      body.appendChild(note(doc, MESSAGES.pending));
      notify(MESSAGES.pending);
    } else if (result.inquiry.ok && !result.candidate.ok) {
      body.appendChild(note(doc, MESSAGES.candidate_unavailable));
      notify(MESSAGES.candidate_unavailable);
    } else if (!result.inquiry.ok) {
      body.appendChild(note(doc, result.inquiry.message));
      notify(result.inquiry.message);
    }
    body.appendChild(h(doc, "div", { class: "button-row" }, [
      actionButton(doc, "skassist-close", "닫기", "primary")
    ]));
  }

  function readForm() {
    var get = function (id) {
      var node = dialog.querySelector("#" + id);
      return node && node.value !== undefined ? String(node.value) : "";
    };
    return {
      name: get("skassist-name"),
      company: get("skassist-company"),
      phone: get("skassist-phone"),
      email: get("skassist-email"),
      note: get("skassist-note")
    };
  }

  function submit() {
    if (!state || state.busy) return;
    var normalized = normalizeRequest(readForm());
    if (!normalized.ok) {
      notify(Manual.MESSAGES[normalized.code] || MESSAGES[normalized.code] || "의뢰 내용을 확인해 주세요.");
      return;
    }
    state.busy = true;
    notify("의뢰와 양식 후보를 접수하고 있습니다.");
    var token = state.token;
    run(normalized.request, {
      fetch: state.env.fetch,
      transport: state.env.transport,
      analyzeFile: state.env.analyzeFile,
      companyProfile: profileOf(state.env),
      extraction: state.extraction,
      fileMeta: state.analysis && state.analysis.ok ? state.meta : null,
      analysis: state.analysis,
      now: new Date().toISOString()
    }).then(function (result) {
      if (!state || state.token !== token) return;
      state.busy = false;
      state.result = result;
      render();
    }).catch(function () {
      if (!state || state.token !== token) return;
      state.busy = false;
      state.result = {
        ok: false,
        request: normalized.request,
        candidate: candidateOutcome(null),
        inquiry: failInquiry("inquiry_request_failed"),
        payload: null
      };
      render();
    });
  }

  function onFileChosen() {
    if (!state || state.busy) return;
    var input = dialog.querySelector("#" + FILE_INPUT_ID);
    var file = input && input.files && input.files[0] ? input.files[0] : null;
    if (!file) return;
    var preflight = Auto.classifyFile(file);
    if (!preflight.ok) {
      notify(Auto.FILE_ERRORS[preflight.error] || "파일을 사용할 수 없습니다.");
      return;
    }
    state.file = file;
    state.meta = preflight.value;
    state.analysis = null;
    state.extraction = null;
    state.busy = true;
    notify("파일을 분석하고 있습니다.");
    var token = state.token;
    Auto.analyzeFile(file, preflight.value, state.env).then(function (result) {
      if (!state || state.token !== token) return;
      state.busy = false;
      if (!result || result.ok !== true) {
        state.analysis = { ok: false, code: result && result.code ? result.code : "analysis_failed" };
        render();
        return;
      }
      state.analysis = { ok: true };
      state.extraction = result.extraction;
      state.draft = Auto.draftFromSources(result.extraction, profileOf(state.env));
      render();
    }).catch(function () {
      if (!state || state.token !== token) return;
      state.busy = false;
      state.analysis = { ok: false, code: "analysis_service_unavailable" };
      render();
    });
  }

  function handleAction(action) {
    if (!state) return;
    if (action === "skassist-signin") {
      if (typeof state.env.openSignIn === "function") state.env.openSignIn();
      else {
        var button = dialog.ownerDocument.getElementById("padiemAccountButton");
        if (button && typeof button.click === "function") button.click();
      }
      return;
    }
    if (action === "skassist-choose") {
      var input = dialog.querySelector("#" + FILE_INPUT_ID);
      if (input && typeof input.click === "function") input.click();
      return;
    }
    if (action === "skassist-submit") { submit(); return; }
    if (action === "skassist-close") {
      state = null;
      if (typeof dialog.close === "function") dialog.close();
      else dialog.hidden = true;
    }
  }

  function open(doc, env, options) {
    var safeEnv = isPlainObject(env) ? env : {};
    ensureDialog(doc);
    var profile = profileOf(safeEnv);
    var draft = Auto.draftFromProfile(profile);
    state = {
      token: 1,
      signedIn: signedIn(safeEnv),
      env: safeEnv,
      draft: draft,
      file: null,
      meta: null,
      extraction: null,
      analysis: null,
      busy: false,
      result: null
    };
    if (dialog.open && typeof dialog.close === "function") dialog.close();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.hidden = false;
    render();
    return {
      close: function () {
        state = null;
        if (typeof dialog.close === "function") dialog.close();
        else dialog.hidden = true;
      },
      state: function () { return state; }
    };
  }

  return {
    DIALOG_ID: DIALOG_ID,
    FILE_INPUT_ID: FILE_INPUT_ID,
    INQUIRY_ENDPOINT: INQUIRY_ENDPOINT,
    CATEGORY: CATEGORY,
    LIMITS: LIMITS,
    MESSAGES: MESSAGES,
    normalizeRequest: normalizeRequest,
    draftFor: draftFor,
    buildInquiryPayload: buildInquiryPayload,
    transportFromFetch: transportFromFetch,
    submitInquiry: submitInquiry,
    run: run,
    open: open
  };
});
