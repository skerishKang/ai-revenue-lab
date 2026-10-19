/* B66 · Quote Beta — quote-skill-auto.js
   견적서 관리 → 새 견적서 만들기 → 기존 파일에서 만들기 (#3186 경로 A)

   정직한 범위:
   - 선택한 파일은 기존 same-origin 추출 seam(SavedQuoteSkillUi.analyzeFile →
     /api/v1/quote/intake)으로만 보낸다. provider/model 선택은 서버 authority다.
   - 인식 결과는 편집 가능한 **초안**이며 후보(candidate)는 저장 전에 사용자가
     직접 확인·수정한다. 자동 layout 학습은 없고 양식은 내장 기본 양식을 쓴다.
   - 승인 요청은 기존 서버 계약(POST /api/padiem/b66/saved-skill-candidates)을
     재사용한다. 브라우저는 승인 상태를 만들 수 없고, 승인 주체는 서버 운영자다.
   - 파일 자동 분석이 꺼져 있거나 실패하면 실패를 그대로 표시하고, 회사 정보를
     직접 확인해 입력한 뒤 같은 승인 요청 경로로 진행할 수 있다.

   (DOM API만 사용 · innerHTML 미사용 · Node 스텁 DOM 으로 테스트) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-skill-registration.js"),
      require("./quote-skill-manual.js"),
      require("./quote-skill-ui.js"),
      require("./file-intake.js")
    );
  } else {
    root.B66QuoteSkillAuto = factory(
      root.SavedQuoteSkillRegistration,
      root.SavedQuoteSkillManual,
      root.SavedQuoteSkillUi,
      root.B66FileIntake
    );
  }
})(typeof self !== "undefined" ? self : this, function (Registration, Manual, SkillUi, FileIntake) {
  "use strict";

  if (!Registration) throw new Error("SavedQuoteSkillRegistration is required");
  if (!Manual) throw new Error("SavedQuoteSkillManual is required");
  if (!SkillUi) throw new Error("SavedQuoteSkillUi is required");
  if (!FileIntake) throw new Error("B66FileIntake is required");

  var AUTO_SOURCE_REF = "file-intake:b66-ui";
  var AUTO_CLIENT_REF_PREFIX = "auto-";
  var CLIENT_REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$/;
  var FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/;
  var CANDIDATE_ID_PATTERN = /^b66cand_[0-9a-f]{32}$/;

  var DIALOG_ID = "skillAutoDialog";
  var TITLE_ID = "skillAutoTitle";
  var STATUS_ID = "skillAutoStatus";
  var BODY_ID = "skillAutoBody";
  var FILE_INPUT_ID = "skauto-file";

  var FILE_ACCEPT = ".pdf,.docx,.pptx,.xlsx,.hwpx,.jpg,.jpeg,.png,.webp";

  var ANALYSIS_UNAVAILABLE =
    "지금은 파일 자동 분석을 사용할 수 없습니다. 회사 정보를 직접 확인해 입력한 뒤 승인 요청을 보낼 수 있습니다.";
  var ANALYSIS_FAILED =
    "파일에서 견적 정보를 읽지 못했습니다. 회사 정보를 직접 확인해 입력한 뒤 승인 요청을 보낼 수 있습니다.";

  var FILE_ERRORS = {
    invalid_file: "파일을 확인하지 못했습니다.",
    invalid_file_name: "파일 이름을 확인해 주세요.",
    invalid_file_size: "파일 크기를 확인하지 못했습니다.",
    empty_file: "빈 파일은 사용할 수 없습니다.",
    legacy_hwp_unsupported: "기존 HWP 파일은 지원하지 않습니다. HWPX 또는 PDF로 저장해 주세요.",
    unsupported_file_type: "지원하지 않는 파일 형식입니다.",
    document_too_large: "문서는 2 MiB 이하만 선택할 수 있습니다.",
    image_too_large: "이미지는 4 MiB 이하만 선택할 수 있습니다.",
    media_extension_mismatch: "파일 확장자와 실제 형식이 일치하지 않습니다.",
    file_read_unavailable: "파일을 읽지 못했습니다. 다시 선택해 주세요.",
    file_size_changed: "선택한 파일이 바뀌었습니다. 다시 선택해 주세요.",
    analysis_service_unavailable: ANALYSIS_UNAVAILABLE,
    analysis_failed: ANALYSIS_FAILED,
    intake_disabled: ANALYSIS_UNAVAILABLE
  };

  var MESSAGES = {
    auth_required: "로그인한 계정에서만 내 견적서 후보를 만들 수 있습니다.",
    invalid_draft: "회사 정보를 확인해 주세요.",
    invalid_extraction: ANALYSIS_FAILED,
    review_required: "검토할 후보가 없습니다. 먼저 입력 후 검토로 이동해 주세요.",
    analysis_pending: "파일을 분석하고 있습니다.",
    analysis_ready: "파일에서 읽은 초안입니다. 값을 확인하고 수정한 뒤 검토로 이동해 주세요.",
    direct_ready: "회사 정보를 직접 확인해 입력합니다.",
    review_ready: "검토 내용을 확인한 뒤 승인 요청을 할 수 있습니다."
  };

  var STEP = Object.freeze({
    CHOOSE: "choose",
    EDIT: "edit",
    REVIEW: "review",
    PENDING: "pending",
    APPROVED: "approved",
    REJECTED: "rejected",
    FAILED: "failed"
  });

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
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

  /* ── 순수 초안/후보 계약 ── */

  function profileValue(profile, key) {
    if (!isPlainObject(profile)) return "";
    var value = profile[key];
    return typeof value === "string" ? value : "";
  }

  function profileDays(profile) {
    var value = isPlainObject(profile) ? profile.defaultValidityDays : null;
    if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 3650) return value;
    return 30;
  }

  function profileTaxMode(profile) {
    var value = isPlainObject(profile) ? profile.defaultTaxMode : "";
    return Manual.TAX_MODES.indexOf(value) >= 0 ? value : "EXCLUSIVE";
  }

  function draftFromProfile(profile) {
    var company = profileValue(profile, "company");
    return {
      name: company ? company + " 견적서" : "우리회사 견적서",
      sender: {
        company: company,
        rep: profileValue(profile, "representative"),
        bizNo: profileValue(profile, "businessNumber"),
        address: profileValue(profile, "address"),
        phone: profileValue(profile, "phone"),
        email: profileValue(profile, "email")
      },
      validDays: profileDays(profile),
      taxMode: profileTaxMode(profile),
      memo: "",
      variableFlags: { memo: true, taxMode: true }
    };
  }

  function textOr(value, fallback) {
    return typeof value === "string" && value.trim() ? value : fallback;
  }

  function daysOr(value, fallback) {
    if (typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 3650) return value;
    if (typeof value === "string" && /^[0-9]{1,4}$/.test(value.trim())) {
      var number = Number(value.trim());
      if (number > 0 && number <= 3650) return number;
    }
    return fallback;
  }

  function draftFromSources(extraction, profile) {
    var base = draftFromProfile(profile);
    if (!isPlainObject(extraction)) return base;
    var facts = SkillUi.factsFromExtraction(extraction);
    if (!facts) return base;
    var sender = facts.sender || {};
    var company = textOr(sender.company, base.sender.company);
    var taxMode = Manual.TAX_MODES.indexOf(facts.taxMode) >= 0 ? facts.taxMode : base.taxMode;
    return {
      name: company ? company + " 견적서" : base.name,
      sender: {
        company: company,
        rep: textOr(sender.rep, base.sender.rep),
        bizNo: textOr(sender.bizNo, base.sender.bizNo),
        address: textOr(sender.address, base.sender.address),
        phone: textOr(sender.phone, base.sender.phone),
        email: textOr(sender.email, base.sender.email)
      },
      validDays: daysOr(facts.validDays, base.validDays),
      taxMode: taxMode,
      memo: typeof facts.memo === "string" ? facts.memo : base.memo,
      variableFlags: { memo: true, taxMode: true }
    };
  }

  function emptyModelOutput(fileMeta) {
    var category = fileMeta && fileMeta.category === "image" ? "image" : "native_document";
    return {
      source: { kind: category, filename: fileMeta && typeof fileMeta.name === "string" ? fileMeta.name : "" },
      sender: { company: null, rep: null, bizNo: null, address: null, phone: null, email: null },
      recipient: { company: null, person: null, address: null, email: null },
      quote: { quoteNo: null, issueDate: null, validDays: null, projectName: null },
      items: [],
      detailGroups: [],
      tax: { mode: null },
      memo: null,
      evidence: [],
      warnings: []
    };
  }

  /* 추출값 위에 사용자가 확인한 값을 덮어써서, 후보의 미확인 목록이 실제로
     확인된 값을 계속 "미확인"으로 표시하지 않게 한다. */
  function reviewedModelOutput(extraction, entry, fileMeta) {
    var base = isPlainObject(extraction) ? cloneJson(extraction) : emptyModelOutput(fileMeta);
    var source = isPlainObject(base.source) ? base.source : {};
    source.kind = fileMeta && fileMeta.category === "image" ? "image"
      : (source.kind || "native_document");
    source.filename = fileMeta && typeof fileMeta.name === "string" ? fileMeta.name : "";
    base.source = source;
    base.sender = {
      company: entry.sender.company,
      rep: entry.sender.rep,
      bizNo: entry.sender.bizNo,
      address: entry.sender.address,
      phone: entry.sender.phone,
      email: entry.sender.email
    };
    base.recipient = isPlainObject(base.recipient) ? base.recipient
      : { company: null, person: null, address: null, email: null };
    base.quote = isPlainObject(base.quote) ? base.quote : { quoteNo: null, issueDate: null, projectName: null };
    base.quote.validDays = entry.validDays > 0 ? entry.validDays : null;
    base.tax = Object.assign({}, isPlainObject(base.tax) ? base.tax : {}, { mode: entry.taxMode });
    base.memo = entry.memo || null;
    if (!Array.isArray(base.items)) base.items = [];
    if (!Array.isArray(base.evidence)) base.evidence = [];
    if (!Array.isArray(base.warnings)) base.warnings = [];
    return base;
  }

  function buildCandidate(draft, options) {
    var opts = options || {};
    var normalized = Manual.normalizeManualEntry(draft);
    if (!normalized.ok) {
      return { ok: false, code: normalized.code, candidate: null, review: null, source: null };
    }
    var entry = normalized.entry;
    var fileMeta = isPlainObject(opts.fileMeta) ? opts.fileMeta : null;
    var extraction = isPlainObject(opts.extraction) ? opts.extraction : null;

    if (!extraction && !fileMeta) {
      var manual = Manual.buildManualCandidate(entry, { now: opts.now });
      if (!manual.ok) {
        return { ok: false, code: manual.code, candidate: null, review: null, source: null };
      }
      return {
        ok: true,
        code: "auto_candidate_ready",
        candidate: manual.candidate,
        review: manual.review,
        entry: entry,
        source: "manual"
      };
    }

    var capturedAt = typeof opts.now === "string" && opts.now ? opts.now.slice(0, 40)
      : new Date().toISOString();
    var corrections = { skillName: entry.name, variableFlags: entry.variableFlags };
    /* 추출 계약은 유효기간 0을 표현하지 못한다. 0일 때만 명시 보정으로 넘긴다. */
    if (entry.validDays === 0) corrections.validDays = 0;
    var built = Registration.buildRegistrationCandidate({
      modelOutput: reviewedModelOutput(extraction, entry, fileMeta),
      corrections: corrections,
      sourceMeta: {
        sourceKind: "file",
        filename: fileMeta && typeof fileMeta.name === "string" ? fileMeta.name : "",
        sourceRef: AUTO_SOURCE_REF,
        capturedAt: capturedAt
      },
      templateDecision: { mode: "builtin" }
    }, { now: capturedAt });
    if (!built.ok || !built.candidate) {
      return {
        ok: false,
        code: built.code || "invalid_extraction",
        candidate: null,
        review: null,
        source: "file"
      };
    }
    return {
      ok: true,
      code: "auto_candidate_ready",
      candidate: built.candidate,
      review: built.review,
      entry: entry,
      source: "file"
    };
  }

  function fnv1a32Hex(text) {
    var hash = 0x811c9dc5;
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      hash = Math.imul(hash ^ (code & 0xff), 0x01000193) >>> 0;
      hash = Math.imul(hash ^ ((code >>> 8) & 0xff), 0x01000193) >>> 0;
    }
    return ("00000000" + hash.toString(16)).slice(-8);
  }

  function clientRefFor(candidate) {
    if (!isPlainObject(candidate)) return null;
    var fingerprint = candidate.skillFingerprint;
    if (typeof fingerprint !== "string" || !FINGERPRINT_PATTERN.test(fingerprint)) return null;
    var name = typeof candidate.name === "string" ? candidate.name : "";
    var ref = AUTO_CLIENT_REF_PREFIX + fingerprint.slice(0, 24) + "-" +
      fnv1a32Hex(fingerprint + "\u0000" + name);
    return CLIENT_REF_PATTERN.test(ref) ? ref : null;
  }

  function transportFor(options) {
    if (typeof options.transport === "function") return options.transport;
    return Manual.transportFromFetch(options.fetch);
  }

  function submitCandidate(candidate, options) {
    var opts = options || {};
    var ref = clientRefFor(candidate);
    if (!ref) {
      return Promise.resolve({
        ok: false, code: "invalid_candidate", approved: false, candidateId: "",
        status: null, savedSkillId: "", rejectionReason: "", decidedAt: "", duplicate: false,
        message: Manual.MESSAGES.invalid_candidate
      });
    }
    return Manual.submitApprovalRequest(candidate, {
      transport: transportFor(opts),
      clientRef: ref
    });
  }

  function fetchCandidateStatus(candidateId, options) {
    var opts = options || {};
    return Manual.fetchApprovalStatus(candidateId, {
      transport: transportFor(opts)
    });
  }

  function analyzeFile(file, fileMeta, options) {
    var opts = options || {};
    if (typeof opts.analyzeFile === "function") return opts.analyzeFile(file, fileMeta, opts.fetch);
    return SkillUi.analyzeFile(file, fileMeta, opts.fetch);
  }

  function classifyFile(file) {
    return FileIntake.classifyFile(file);
  }

  function analysisFailureMessage(code) {
    return FILE_ERRORS[code] || ANALYSIS_FAILED;
  }

  function stepForStatus(status) {
    if (status === "pending") return STEP.PENDING;
    if (status === "approved") return STEP.APPROVED;
    if (status === "rejected") return STEP.REJECTED;
    return STEP.FAILED;
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

  function notify(stateValue, message) {
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
    dialog.className = "b66-skill-start-dialog b66-skill-auto-dialog";
    dialog.setAttribute("aria-labelledby", TITLE_ID);
    var heading = h(doc, "div", { class: "b66-skill-start-heading" }, []);
    heading.appendChild(h(doc, "h2", { id: TITLE_ID, text: "기존 파일로 내 견적서 만들기" }, []));
    var close = h(doc, "button", { type: "button", text: "닫기" }, []);
    close.setAttribute("aria-label", "파일로 만들기 닫기");
    close.addEventListener("click", function () {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.hidden = true;
    });
    heading.appendChild(close);
    dialog.appendChild(heading);
    dialog.appendChild(note(doc,
      "선택한 파일은 견적 정보 추출을 위해 같은 서비스의 기존 분석 경로로 전송됩니다. " +
      "인식 결과는 초안이며, 저장 전에 직접 확인·수정합니다. 승인은 운영자가 합니다."));
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

  function bodyNode() {
    return dialog.querySelector("#" + BODY_ID);
  }

  function render() {
    if (!dialog || !state) return;
    var doc = dialog.ownerDocument;
    var body = bodyNode();
    clear(body);
    if (!state.signedIn) {
      body.appendChild(note(doc,
        "기존 파일로 만들기는 로그인한 계정에서만 사용할 수 있습니다. " +
        "로그인하면 파일에서 읽은 초안을 확인해 내 견적서 후보로 준비할 수 있습니다."));
      body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "skauto-signin", "로그인", "primary")
      ]));
      notify(state, MESSAGES.auth_required);
      return;
    }
    if (state.step === STEP.EDIT) { renderEditor(doc, body); return; }
    if (state.step === STEP.REVIEW) { renderReview(doc, body); return; }
    if (state.step === STEP.PENDING || state.step === STEP.APPROVED ||
        state.step === STEP.REJECTED || state.step === STEP.FAILED) {
      renderOutcome(doc, body);
      return;
    }
    renderChooser(doc, body);
  }

  function fileSummary(doc) {
    if (!state.meta) return note(doc, "선택한 파일이 없습니다.");
    var status = state.analysis && state.analysis.ok
      ? "자동 분석 완료"
      : state.analysis && state.analysis.code
        ? "자동 분석 사용 불가 (" + state.analysis.code + ")"
        : "분석 전";
    return dl(doc, [
      ["파일", state.meta.name],
      ["형식", state.meta.label],
      ["크기", state.meta.displaySize],
      ["자동 분석", status]
    ]);
  }

  function renderChooser(doc, body) {
    body.appendChild(note(doc,
      "기존 견적서 파일을 선택하면 회사 정보와 기본값을 초안으로 채웁니다. " +
      "파일 자동 분석이 꺼져 있어도 회사 정보를 직접 확인해 후보를 만들 수 있습니다."));
    body.appendChild(fileSummary(doc));
    var input = h(doc, "input", {
      id: FILE_INPUT_ID, type: "file", accept: FILE_ACCEPT, hidden: true
    }, []);
    input.addEventListener("change", onFileChosen);
    body.appendChild(input);
    var buttons = [
      actionButton(doc, "skauto-choose", state.meta ? "다른 파일 선택" : "파일 선택", "primary"),
      actionButton(doc, "skauto-direct", "회사 정보 직접 입력", "soft")
    ];
    if (state.meta && state.analysis && state.analysis.ok) {
      buttons.splice(1, 0, actionButton(doc, "skauto-edit", "초안 확인", "primary"));
    }
    if (state.meta && state.busy) buttons.unshift(actionButton(doc, "skauto-busy", "분석 중", "soft"));
    body.appendChild(h(doc, "div", { class: "button-row" }, buttons));
    if (!state.busy) notify(state, state.analysis && state.analysis.code
      ? analysisFailureMessage(state.analysis.code)
      : "파일을 선택하거나 회사 정보를 직접 입력해 주세요.");
  }

  function renderEditor(doc, body) {
    var entry = state.draft;
    body.appendChild(note(doc, state.extraction
      ? "파일에서 읽은 값을 초안으로 채웠습니다. 실제와 다른 값은 직접 수정해 주세요."
      : "회사 정보를 직접 확인해 입력합니다. 거래처·견적번호·작성일·품목은 견적마다 따로 입력합니다."));
    if (state.meta) body.appendChild(fileSummary(doc));
    var form = h(doc, "div", { class: "fields" }, []);
    [["skauto-name", "내 견적서 이름", entry.name, Manual.LIMITS.name],
     ["skauto-company", "회사명", entry.sender.company, Manual.LIMITS.company],
     ["skauto-rep", "대표자", entry.sender.rep, Manual.LIMITS.rep],
     ["skauto-bizno", "사업자번호", entry.sender.bizNo, Manual.LIMITS.bizNo],
     ["skauto-address", "주소", entry.sender.address, Manual.LIMITS.address],
     ["skauto-phone", "연락처", entry.sender.phone, Manual.LIMITS.phone],
     ["skauto-email", "이메일", entry.sender.email, Manual.LIMITS.email]
    ].forEach(function (spec) {
      var label = h(doc, "label", { htmlFor: spec[0] }, [spec[1] + " "]);
      label.appendChild(textInput(doc, spec[0], spec[2], { maxlength: String(spec[3]) }));
      form.appendChild(label);
    });
    var daysLabel = h(doc, "label", { htmlFor: "skauto-valid-days" }, ["기본 유효기간(일) "]);
    daysLabel.appendChild(textInput(doc, "skauto-valid-days", String(entry.validDays), { inputmode: "numeric" }));
    form.appendChild(daysLabel);
    var taxLabel = h(doc, "label", { htmlFor: "skauto-tax-mode" }, ["기본 세금 방식 "]);
    var taxSelect = h(doc, "select", { id: "skauto-tax-mode" }, []);
    Manual.TAX_MODES.forEach(function (mode) {
      var option = h(doc, "option", { value: mode, text: mode }, []);
      if (mode === entry.taxMode) option.selected = true;
      taxSelect.appendChild(option);
    });
    taxLabel.appendChild(taxSelect);
    form.appendChild(taxLabel);
    body.appendChild(form);
    var memoLabel = h(doc, "label", { htmlFor: "skauto-memo" }, ["기본 비고 "]);
    memoLabel.appendChild(h(doc, "textarea", { id: "skauto-memo", value: entry.memo }, []));
    body.appendChild(h(doc, "div", { class: "fields" }, [memoLabel]));
    var flags = h(doc, "div", { class: "fields" }, []);
    var memoFlag = h(doc, "label", {}, []);
    memoFlag.appendChild(h(doc, "input", { id: "skauto-flag-memo", type: "checkbox",
      checked: entry.variableFlags.memo === true }, []));
    memoFlag.appendChild(doc.createTextNode(" 건별 비고 입력 허용"));
    flags.appendChild(memoFlag);
    var taxFlag = h(doc, "label", {}, []);
    taxFlag.appendChild(h(doc, "input", { id: "skauto-flag-taxmode", type: "checkbox",
      checked: entry.variableFlags.taxMode === true }, []));
    taxFlag.appendChild(doc.createTextNode(" 건별 세금 방식 변경 허용"));
    flags.appendChild(taxFlag);
    body.appendChild(flags);
    body.appendChild(h(doc, "div", { class: "button-row" }, [
      actionButton(doc, "skauto-restart", "파일 다시 선택", "soft"),
      actionButton(doc, "skauto-review", "다음: 검토", "primary")
    ]));
    notify(state, state.analysis && state.analysis.code
      ? analysisFailureMessage(state.analysis.code)
      : state.extraction ? MESSAGES.analysis_ready : MESSAGES.direct_ready);
  }

  function renderReview(doc, body) {
    var review = state.review;
    body.appendChild(h(doc, "h4", { text: "A. 출처" }, []));
    body.appendChild(dl(doc, [
      ["입력 방식", state.source === "file" ? "기존 파일 + 사용자 확인" : "직접 입력"],
      ["파일", state.meta ? state.meta.name : "(없음)"],
      ["후보 이름", review.name],
      ["후보 상태", "승인 전 후보"],
      ["확인 필요", review.source.unknowns.join("; ") || "없음"]
    ]));
    body.appendChild(h(doc, "h4", { text: "B. 항상 다시 사용하는 값" }, []));
    body.appendChild(dl(doc, review.alwaysReusedOrDefault.map(function (row) {
      return [row.label, row.value === "" || row.value === null ? "(비어 있음)" : row.value];
    })));
    body.appendChild(h(doc, "h4", { text: "C. 견적마다 바뀌는 값 (저장하지 않음)" }, []));
    body.appendChild(dl(doc, review.changesEachQuote.map(function (row) {
      return [row.label, row.required ? "필수 입력" : "선택 입력"];
    })));
    body.appendChild(h(doc, "h4", { text: "D. 자동 계산" }, []));
    body.appendChild(dl(doc, review.calculatedByCore.map(function (row) {
      return [row.key, row.authority];
    })));
    body.appendChild(note(doc,
      "출력 양식은 내장 기본 견적서 양식을 사용합니다. 자동 layout 학습은 없습니다. " +
      "승인 요청은 권한 있는 운영자가 검토하며, 승인 전에는 내 견적서로 사용할 수 없습니다."));
    body.appendChild(h(doc, "div", { class: "button-row" }, [
      actionButton(doc, "skauto-edit", "수정하러 가기", "soft"),
      actionButton(doc, "skauto-submit", "승인 요청", "primary")
    ]));
    notify(state, MESSAGES.review_ready);
  }

  function renderOutcome(doc, body) {
    var approval = state.approval;
    var title = "승인 요청";
    var message = "";
    var rows = [["후보 이름", state.review ? state.review.name : ""]];
    var buttons = [];
    if (state.step === STEP.PENDING) {
      title = "승인 대기";
      message = Manual.APPROVAL_PENDING_MESSAGE;
      rows.push(["상태", "승인 대기 · 아직 사용할 수 없음"]);
      if (approval.candidateId) rows.push(["승인 요청 ID", approval.candidateId]);
      buttons.push(actionButton(doc, "skauto-refresh", "상태 새로고침"));
      buttons.push(actionButton(doc, "skauto-edit", "수정하러 가기", "soft"));
    } else if (state.step === STEP.APPROVED) {
      title = "승인 완료";
      message = Manual.APPROVAL_APPROVED_MESSAGE;
      rows.push(["상태", "승인 완료 · 사용 가능"]);
      if (approval.savedSkillId) rows.push(["배정된 내 견적서", approval.savedSkillId]);
      if (approval.decidedAt) rows.push(["승인 시각", approval.decidedAt]);
      buttons.push(actionButton(doc, "skauto-refresh-skills", "내 견적서 목록 새로고침", "primary"));
    } else if (state.step === STEP.REJECTED) {
      title = "승인 거부";
      message = Manual.APPROVAL_REJECTED_MESSAGE;
      rows.push(["상태", "승인 거부 · 사용 불가"]);
      rows.push(["거부 사유", approval.rejectionReason || "(사유 없음)"]);
      if (approval.decidedAt) rows.push(["거부 시각", approval.decidedAt]);
      buttons.push(actionButton(doc, "skauto-edit", "수정하러 가기", "primary"));
    } else {
      title = "승인 요청 실패";
      message = approval.message || Manual.APPROVAL_FAILED_MESSAGE;
      rows.push(["상태", "요청이 접수되지 않았습니다"]);
      if (approval.code) rows.push(["오류 코드", approval.code]);
      buttons.push(actionButton(doc, "skauto-submit", "다시 요청", "primary"));
      buttons.push(actionButton(doc, "skauto-edit", "수정하러 가기", "soft"));
    }
    body.appendChild(h(doc, "p", { class: "template-manage-note", text: title }, []));
    body.appendChild(dl(doc, rows));
    body.appendChild(note(doc, message));
    body.appendChild(h(doc, "div", { class: "button-row" }, buttons));
    notify(state, message);
  }

  function readForm() {
    var get = function (id) {
      var node = dialog.querySelector("#" + id);
      return node && node.value !== undefined ? String(node.value) : "";
    };
    var checked = function (id) {
      var node = dialog.querySelector("#" + id);
      return Boolean(node && node.checked);
    };
    return {
      name: get("skauto-name"),
      sender: {
        company: get("skauto-company"),
        rep: get("skauto-rep"),
        bizNo: get("skauto-bizno"),
        address: get("skauto-address"),
        phone: get("skauto-phone"),
        email: get("skauto-email")
      },
      validDays: get("skauto-valid-days"),
      taxMode: get("skauto-tax-mode"),
      memo: get("skauto-memo"),
      variableFlags: { memo: checked("skauto-flag-memo"), taxMode: checked("skauto-flag-taxmode") }
    };
  }

  function goReview() {
    var normalized = Manual.normalizeManualEntry(readForm());
    if (!normalized.ok) {
      notify(state, Manual.MESSAGES[normalized.code] || MESSAGES.invalid_draft);
      return;
    }
    var built = buildCandidate(normalized.entry, {
      extraction: state.extraction,
      fileMeta: state.meta,
      now: new Date().toISOString()
    });
    if (!built.ok || !built.candidate) {
      notify(state, Manual.MESSAGES[built.code] || analysisFailureMessage(built.code) || MESSAGES.invalid_draft);
      state.analysis = { ok: false, code: built.code };
      state.step = STEP.EDIT;
      render();
      return;
    }
    state.draft = normalized.entry;
    state.candidate = built.candidate;
    state.review = built.review;
    state.source = built.source;
    state.step = STEP.REVIEW;
    state.approval = {};
    render();
  }

  function applyResult(result) {
    state.candidateId = result.candidateId;
    state.approval = {
      candidateId: result.candidateId,
      status: result.status,
      savedSkillId: result.savedSkillId,
      rejectionReason: result.rejectionReason,
      decidedAt: result.decidedAt,
      code: result.ok ? "" : result.code,
      message: result.ok ? "" : result.message
    };
    state.step = result.ok ? stepForStatus(result.status) : STEP.FAILED;
    state.busy = false;
    render();
    if (state.step === STEP.APPROVED && typeof state.env.refreshAssignedSkills === "function") {
      state.env.refreshAssignedSkills();
    }
  }

  function submit() {
    if (!state || state.busy) return;
    if (!state.candidate) {
      notify(state, MESSAGES.review_required);
      return;
    }
    state.busy = true;
    notify(state, "승인 요청을 보내고 있습니다.");
    submitCandidate(state.candidate, state.env).then(applyResult).catch(function () {
      applyResult({ ok: false, code: "approval_request_failed", message: Manual.APPROVAL_FAILED_MESSAGE });
    });
  }

  function refresh() {
    if (!state || state.busy || !CANDIDATE_ID_PATTERN.test(state.candidateId || "")) return;
    state.busy = true;
    notify(state, "승인 상태를 확인하고 있습니다.");
    fetchCandidateStatus(state.candidateId, state.env).then(applyResult).catch(function () {
      applyResult({ ok: false, code: "approval_request_failed", message: Manual.APPROVAL_FAILED_MESSAGE });
    });
  }

  function onFileChosen() {
    if (!state || state.busy) return;
    var input = dialog.querySelector("#" + FILE_INPUT_ID);
    var file = input && input.files && input.files[0] ? input.files[0] : null;
    if (!file) return;
    var preflight = classifyFile(file);
    if (!preflight.ok) {
      notify(state, FILE_ERRORS[preflight.error] || "파일을 사용할 수 없습니다.");
      return;
    }
    state.file = file;
    state.meta = preflight.value;
    state.extraction = null;
    state.analysis = null;
    analyze();
  }

  function analyze() {
    if (!state || state.busy || !state.file || !state.meta) return;
    state.busy = true;
    state.step = STEP.CHOOSE;
    notify(state, MESSAGES.analysis_pending);
    var token = state.token;
    analyzeFile(state.file, state.meta, state.env).then(function (result) {
      if (!state || state.token !== token) return;
      state.busy = false;
      if (!result || result.ok !== true) {
        state.extraction = null;
        state.analysis = { ok: false, code: result && result.code ? result.code : "analysis_failed" };
        state.draft = draftFromProfile(profileOf(state.env));
        state.step = STEP.EDIT;
        render();
        return;
      }
      state.extraction = result.extraction;
      state.analysis = { ok: true };
      state.draft = draftFromSources(result.extraction, profileOf(state.env));
      state.step = STEP.EDIT;
      render();
    }).catch(function () {
      if (!state || state.token !== token) return;
      state.busy = false;
      state.analysis = { ok: false, code: "analysis_service_unavailable" };
      state.extraction = null;
      state.draft = draftFromProfile(profileOf(state.env));
      state.step = STEP.EDIT;
      render();
    });
  }

  function handleAction(action) {
    if (!state) return;
    if (action === "skauto-signin") {
      if (typeof state.env.openSignIn === "function") state.env.openSignIn();
      else {
        var button = dialog.ownerDocument.getElementById("padiemAccountButton");
        if (button && typeof button.click === "function") button.click();
      }
      return;
    }
    if (action === "skauto-choose") {
      var input = dialog.querySelector("#" + FILE_INPUT_ID);
      if (input && typeof input.click === "function") input.click();
      return;
    }
    if (action === "skauto-direct") {
      state.step = STEP.EDIT;
      state.extraction = null;
      state.analysis = null;
      state.draft = draftFromProfile(profileOf(state.env));
      render();
      return;
    }
    if (action === "skauto-restart") {
      state.token += 1;
      state.step = STEP.CHOOSE;
      state.file = null;
      state.meta = null;
      state.extraction = null;
      state.analysis = null;
      state.busy = false;
      state.draft = draftFromProfile(profileOf(state.env));
      render();
      return;
    }
    if (action === "skauto-review") { goReview(); return; }
    if (action === "skauto-edit") {
      state.step = STEP.EDIT;
      state.busy = false;
      render();
      return;
    }
    if (action === "skauto-submit") { submit(); return; }
    if (action === "skauto-refresh") { refresh(); return; }
    if (action === "skauto-refresh-skills") {
      if (typeof state.env.refreshAssignedSkills === "function") state.env.refreshAssignedSkills();
      notify(state, "내 견적서 목록을 다시 읽었습니다.");
    }
  }

  function open(doc, env, options) {
    var opts = options || {};
    var safeEnv = isPlainObject(env) ? env : {};
    ensureDialog(doc);
    var authenticated = signedIn(safeEnv);
    state = {
      token: 1,
      step: STEP.CHOOSE,
      signedIn: authenticated,
      env: safeEnv,
      file: null,
      meta: null,
      extraction: null,
      analysis: null,
      draft: draftFromProfile(profileOf(safeEnv)),
      candidate: null,
      candidateId: "",
      review: null,
      source: null,
      approval: {},
      busy: false
    };
    if (dialog.open && typeof dialog.close === "function") dialog.close();
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.hidden = false;
    render();
    if (authenticated && opts.file) {
      var preflight = classifyFile(opts.file);
      if (!preflight.ok) {
        notify(state, FILE_ERRORS[preflight.error] || "파일을 사용할 수 없습니다.");
      } else {
        state.file = opts.file;
        state.meta = preflight.value;
        analyze();
      }
    }
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
    AUTO_SOURCE_REF: AUTO_SOURCE_REF,
    STEP: STEP,
    MESSAGES: MESSAGES,
    FILE_ERRORS: FILE_ERRORS,
    ANALYSIS_UNAVAILABLE: ANALYSIS_UNAVAILABLE,
    ANALYSIS_FAILED: ANALYSIS_FAILED,
    draftFromProfile: draftFromProfile,
    draftFromSources: draftFromSources,
    reviewedModelOutput: reviewedModelOutput,
    buildCandidate: buildCandidate,
    clientRefFor: clientRefFor,
    submitCandidate: submitCandidate,
    fetchCandidateStatus: fetchCandidateStatus,
    classifyFile: classifyFile,
    analyzeFile: analyzeFile,
    analysisFailureMessage: analysisFailureMessage,
    open: open
  };
});
