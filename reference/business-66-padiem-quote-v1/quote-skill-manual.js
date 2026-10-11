/* B66 · Quote Beta — quote-skill-manual.js
   견적서 관리 → 새 견적서 만들기 → 직접 만들기 (#4319, 상위 #3186 경로 B)

   정직한 범위:
   - 로그인한 사용자가 직접 입력한 회사 기본값으로 Saved Quote Skill **후보(candidate)**
     를 준비한다. 후보는 검토 대상일 뿐이고, 승인된 Saved Quote Skill 이 아니다.
   - 브라우저에 보존되는 것은 bounded 초안(entry)뿐이다. 승인 Skill 저장소
     (SavedQuoteSkillStore)에는 절대 쓰지 않으므로, 미승인 후보가 승인 완료된
     내 견적서처럼 목록에 나타나지 않는다.
   - 고객용 승인 요청 서버 API 는 현재 존재하지 않는다(APPROVAL_ENDPOINT = null).
     따라서 상태는 항상 "승인 요청 연결 전" 이고, 요청은 fail closed 로 실패한다.
     가짜 성공 · 자동 승인 · 소유자(owner) 권한 자동 부여를 하지 않는다.
   - 계산 authority 는 QuoteCore, 양식·렌더 authority 는 기존 QuoteTemplate /
     SavedQuoteSkill 계약을 재사용한다. 새 계산기·렌더러·승인 경로를 만들지 않는다.

   필요한 백엔드 작업(미구현 · 후속): 승인 권한을 가진 서버가 후보 지문
   (skillFingerprint)과 요청자 신원을 검증해 승인하는 endpoint. 이것이 없으면
   어떤 화면 상태도 "승인됨"으로 표시할 수 없다.

   (DOM API만 사용 · innerHTML 미사용 · Node 스텁 DOM 으로 전부 테스트) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-skill.js"),
      require("./quote-skill-candidate.js"),
      require("./quote-skill-registration.js"),
      require("./quote-extraction.js")
    );
  } else {
    root.SavedQuoteSkillManual = factory(
      root.SavedQuoteSkill,
      root.SavedQuoteSkillCandidate,
      root.SavedQuoteSkillRegistration,
      root.QuoteExtraction
    );
  }
})(typeof self !== "undefined" ? self : this, function (
  Skill, SkillCandidate, SkillRegistration, Extraction
) {
  "use strict";

  if (!Skill) throw new Error("SavedQuoteSkill is required");
  if (!SkillCandidate) throw new Error("SavedQuoteSkillCandidate is required");
  if (!SkillRegistration) throw new Error("SavedQuoteSkillRegistration is required");
  if (!Extraction) throw new Error("QuoteExtraction is required");

  var MANUAL_DRAFT_STORAGE_KEY = "quoteBeta.manualSkillDraft.v1";
  var DRAFT_SCHEMA_VERSION = 1;

  /* Skill 수준 출처는 "manual". 추출 계약에는 "manual" kind 가 없으므로
     사용자가 직접 타이핑한 텍스트인 "text" 를 쓴다. 파일·스캔 원본이 아니다. */
  var MANUAL_EXTRACTION_SOURCE_KIND = "text";
  var MANUAL_SOURCE_KIND = "manual";
  var MANUAL_SOURCE_REF = "manual-entry:b66-ui";
  var MANUAL_SOURCE_LABEL = "직접 입력";

  /* 고객용 승인 요청 endpoint. 현재 없음 — null 이 곧 진실이다. */
  var APPROVAL_ENDPOINT = null;
  var APPROVAL_NOT_CONNECTED_MESSAGE =
    "승인 요청 연결 전입니다. 저장된 것은 초안 후보이며, 아직 내 견적서로 사용할 수 없습니다.";
  var BACKEND_PREREQUISITE =
    "필요 백엔드: 후보 지문(skillFingerprint)과 요청자 신원을 검증하는 승인 권한 서버 endpoint";

  var STATUS = Object.freeze({
    DRAFT: "draft",
    REVIEW: "review",
    APPROVAL_NOT_CONNECTED: "approval_not_connected"
  });

  var TAX_MODES = ["EXCLUSIVE", "INCLUSIVE", "EXEMPT"];
  var LIMITS = Object.freeze({
    name: Skill.MAX_SKILL_NAME_CHARS || 80,
    company: 120,
    rep: 60,
    bizNo: 40,
    address: 200,
    phone: 40,
    email: 160,
    memo: 400,
    validDaysMax: 3650
  });
  var MAX_DRAFT_CHARS = 8000;

  var IDS = {
    panel: "skillManualPanel",
    title: "skillManualTitle",
    status: "skillManualStatus",
    body: "skillManualBody",
    close: "skillManualClose"
  };

  var MESSAGES = {
    manual_entry_required: "직접 만들기 값을 입력해 주세요.",
    invalid_manual_name: "내 견적서 이름을 확인해 주세요.",
    invalid_manual_sender_company: "회사명을 입력해 주세요.",
    invalid_manual_valid_days: "기본 유효기간(일)을 0~3650 사이로 입력해 주세요.",
    invalid_manual_tax_mode: "기본 세금 방식을 선택해 주세요.",
    invalid_manual_variable_flags: "견적마다 바뀌는 값 설정을 확인해 주세요.",
    invalid_skill_candidate: "후보를 만들지 못했습니다. 입력값을 확인해 주세요.",
    approval_endpoint_unavailable: APPROVAL_NOT_CONNECTED_MESSAGE,
    candidate_not_submittable: "검토할 후보가 없습니다. 먼저 입력 후 검토로 이동해 주세요."
  };

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function fail(code) {
    return { ok: false, code: code, message: MESSAGES[code] || null, entry: null };
  }

  /* 제어문자 제거 + 길이 제한. 개행은 여러 줄 입력(비고)에서만 유지한다. */
  function sanitizeText(value, maxChars, keepNewline) {
    if (value === null || value === undefined) return "";
    if (typeof value !== "string") return "";
    var pattern = keepNewline ? /[\u0000-\u0009\u000b-\u001f\u007f]/g : /[\u0000-\u001f\u007f]/g;
    return value.replace(pattern, " ").trim().slice(0, maxChars);
  }

  function normalizeValidDays(value) {
    var text = "";
    if (typeof value === "number" && Number.isFinite(value)) text = String(Math.round(value));
    else if (typeof value === "string") text = value.trim();
    if (!text) return null;
    if (!/^[0-9]{1,4}$/.test(text)) return null;
    var number = Number(text);
    if (!Number.isFinite(number) || number < 0 || number > LIMITS.validDaysMax) return null;
    return Math.round(number);
  }

  function normalizeFlags(raw) {
    var source = isPlainObject(raw) ? raw : {};
    return {
      memo: source.memo === true,
      taxMode: source.taxMode === true
    };
  }

  function normalizeManualEntry(raw) {
    if (!isPlainObject(raw)) return fail("manual_entry_required");
    if (!isPlainObject(raw.sender)) return fail("manual_entry_required");

    var name = sanitizeText(raw.name, LIMITS.name, false);
    if (!name) return fail("invalid_manual_name");

    var company = sanitizeText(raw.sender.company, LIMITS.company, false);
    if (!company) return fail("invalid_manual_sender_company");

    var validDays = normalizeValidDays(raw.validDays);
    if (validDays === null) return fail("invalid_manual_valid_days");

    var taxMode = typeof raw.taxMode === "string" ? raw.taxMode.trim().toUpperCase() : "";
    if (TAX_MODES.indexOf(taxMode) === -1) return fail("invalid_manual_tax_mode");

    var flags = normalizeFlags(raw.variableFlags);
    if (!isPlainObject(raw.variableFlags) && raw.variableFlags !== undefined) {
      return fail("invalid_manual_variable_flags");
    }

    return {
      ok: true,
      code: "manual_entry_ready",
      message: null,
      entry: {
        schemaVersion: DRAFT_SCHEMA_VERSION,
        name: name,
        sender: {
          company: company,
          rep: sanitizeText(raw.sender.rep, LIMITS.rep, false),
          bizNo: sanitizeText(raw.sender.bizNo, LIMITS.bizNo, false),
          address: sanitizeText(raw.sender.address, LIMITS.address, false),
          phone: sanitizeText(raw.sender.phone, LIMITS.phone, false),
          email: sanitizeText(raw.sender.email, LIMITS.email, false)
        },
        validDays: validDays,
        taxMode: taxMode,
        memo: sanitizeText(raw.memo, LIMITS.memo, true),
        variableFlags: flags
      }
    };
  }

  /* 견적마다 바뀌는 값은 후보에 저장하지 않는다. 추출 계약이 그 값을 "미확인"으로
     세는 것은 파일 원본 기준이므로, 직접 입력 경로에서는 해당 항목만 제외한다. */
  var PER_QUOTE_UNKNOWN_PREFIXES = [
    "recipient.",
    "quote.quoteNo",
    "quote.issueDate",
    "items",
    /* 직접 입력 경로에서 잘린 경고는 모두 위 보정 노이즈이므로 함께 정리한다. */
    "additional_model_warnings:"
  ];

  function filterPerQuoteUnknowns(unknowns) {
    return (unknowns || []).filter(function (note) {
      if (typeof note !== "string") return true;
      return !PER_QUOTE_UNKNOWN_PREFIXES.some(function (prefix) {
        return note === prefix || note.indexOf(prefix) === 0;
      });
    });
  }

  /* 직접 입력 경로는 모든 값이 사용자 입력이므로 "보정됨" 표시는 정보가 없다.
     남겨두면 실제 경고가 잘려나가므로 이 접두 항목만 정리한다. 값 자체는
     검토 화면 B 항목에 그대로 노출된다. */
  function filterCorrectionNoise(warnings) {
    return (warnings || []).filter(function (note) {
      return typeof note !== "string" || note.indexOf("manual_correction:") !== 0;
    });
  }

  function manualModelOutput(entry) {
    return {
      source: { kind: MANUAL_EXTRACTION_SOURCE_KIND, filename: "" },
      sender: {
        company: entry.sender.company,
        rep: entry.sender.rep,
        bizNo: entry.sender.bizNo,
        address: entry.sender.address,
        phone: entry.sender.phone,
        email: entry.sender.email
      },
      recipient: { company: null, person: null, address: null, email: null },
      quote: { quoteNo: null, issueDate: null, validDays: entry.validDays, projectName: null },
      items: [],
      tax: { mode: entry.taxMode },
      memo: entry.memo,
      evidence: [],
      warnings: []
    };
  }

  /* 후보 생성: 기존 SavedQuoteSkillRegistration 이 최종 검증 authority 다.
     양식은 내장 승인 양식(builtin)만 사용한다. 자동 레이아웃 학습은 없다. */
  function buildManualCandidate(entry, options) {
    var opts = options || {};
    var normalized = normalizeManualEntry(entry);
    if (!normalized.ok) {
      return { ok: false, code: normalized.code, candidate: null, review: null };
    }
    var value = normalized.entry;
    var capturedAt = typeof opts.now === "string" && opts.now ? opts.now.slice(0, 40) : "";

    var built = SkillRegistration.buildRegistrationCandidate({
      modelOutput: manualModelOutput(value),
      corrections: {
        sender: {
          company: value.sender.company,
          rep: value.sender.rep,
          bizNo: value.sender.bizNo,
          address: value.sender.address,
          phone: value.sender.phone,
          email: value.sender.email
        },
        validDays: value.validDays,
        taxMode: value.taxMode,
        memo: value.memo,
        skillName: value.name,
        variableFlags: value.variableFlags
      },
      sourceMeta: {
        sourceKind: MANUAL_SOURCE_KIND,
        sourceName: value.name,
        sourceRef: MANUAL_SOURCE_REF,
        capturedAt: capturedAt
      },
      templateDecision: { mode: "builtin" }
    }, opts);
    if (!built.ok || !built.candidate) {
      return { ok: false, code: built.code || "invalid_skill_candidate", candidate: null, review: null };
    }

    /* 후보 경계(authority)를 다시 통과시켜 미확인 목록만 정리한다. 값·지문은
       동일 계약으로 재계산되므로 임의 조작이 아니다. */
    var provenance = built.candidate.provenance;
    var refined = SkillCandidate.normalizeCandidate({
      schemaVersion: SkillCandidate.CANDIDATE_SCHEMA_VERSION,
      candidateId: built.candidate.candidateId,
      name: built.candidate.name,
      fixedDefaults: built.candidate.fixedDefaults,
      variableSchema: built.candidate.variableSchema,
      internalTemplate: built.candidate.internalTemplate,
      provenance: {
        sourceKind: provenance.sourceKind,
        sourceName: MANUAL_SOURCE_LABEL,
        sourceRef: provenance.sourceRef,
        capturedAt: provenance.capturedAt,
        warnings: filterCorrectionNoise(provenance.warnings),
        unknowns: filterPerQuoteUnknowns(provenance.unknowns),
        evidence: provenance.evidence.slice()
      }
    }, opts);
    var candidate = refined.ok ? refined.candidate : built.candidate;

    return {
      ok: true,
      code: "manual_candidate_ready",
      candidate: candidate,
      review: SkillCandidate.buildReviewModel(candidate),
      entry: value
    };
  }

  /* ── 승인 요청 계약 (현재 연결 없음 → 항상 fail closed) ── */

  function approvalRequestState() {
    return {
      connected: APPROVAL_ENDPOINT !== null,
      endpoint: APPROVAL_ENDPOINT,
      code: APPROVAL_ENDPOINT === null ? "approval_endpoint_unavailable" : "approval_endpoint_configured",
      message: APPROVAL_NOT_CONNECTED_MESSAGE,
      backendPrerequisite: BACKEND_PREREQUISITE
    };
  }

  function failRequest(code, state) {
    return {
      ok: false,
      code: code,
      approved: false,
      skill: null,
      status: STATUS.APPROVAL_NOT_CONNECTED,
      state: state,
      message: MESSAGES[code] || null
    };
  }

  /* 승인은 서버 authority 전용이다. 미연결이면 어떤 성공도 만들지 않는다. */
  function requestApproval(candidate, options) {
    void options;
    var state = approvalRequestState();
    if (!candidate || candidate.status !== SkillCandidate.STATUS_CANDIDATE) {
      return failRequest("candidate_not_submittable", state);
    }
    if (state.connected !== true) {
      return failRequest(state.code, state);
    }
    /* Endpoint 가 연결되는 날에도 이 모듈은 스스로 승인을 만들지 않는다. */
    return failRequest("approval_request_not_implemented", state);
  }

  /* ── 초안 보존 (bounded, 실패 시 폐쇄) ── */

  function readManualDraft(storage) {
    if (!storage || typeof storage.getItem !== "function") return null;
    var raw;
    try {
      raw = storage.getItem(MANUAL_DRAFT_STORAGE_KEY);
    } catch (err) {
      return null;
    }
    if (!raw || typeof raw !== "string" || raw.length > MAX_DRAFT_CHARS) return null;
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      return null;
    }
    if (!isPlainObject(parsed) || parsed.schemaVersion !== DRAFT_SCHEMA_VERSION) return null;
    var normalized = normalizeManualEntry(parsed.entry);
    if (!normalized.ok) return null;
    var status = parsed.status === STATUS.REVIEW || parsed.status === STATUS.APPROVAL_NOT_CONNECTED
      ? parsed.status
      : STATUS.DRAFT;
    return {
      schemaVersion: DRAFT_SCHEMA_VERSION,
      status: status,
      entry: normalized.entry,
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt.slice(0, 40) : ""
    };
  }

  function writeManualDraft(storage, draft) {
    if (!storage || typeof storage.setItem !== "function") return false;
    if (!isPlainObject(draft)) return false;
    var serialized;
    try {
      serialized = JSON.stringify(draft);
    } catch (err) {
      return false;
    }
    if (!serialized || serialized.length > MAX_DRAFT_CHARS) return false;
    try {
      storage.setItem(MANUAL_DRAFT_STORAGE_KEY, serialized);
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearManualDraft(storage) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    try {
      storage.removeItem(MANUAL_DRAFT_STORAGE_KEY);
      return true;
    } catch (err) {
      return false;
    }
  }

  /* ── DOM 바인딩 ── */

  function h(doc, tag, attrs, children) {
    var node = doc.createElement(tag);
    var safe = attrs || {};
    Object.keys(safe).forEach(function (key) {
      if (key === "text") {
        node.textContent = String(safe[key]);
      } else if (key === "hidden") {
        node.hidden = Boolean(safe[key]);
      } else if (key === "htmlFor") {
        node.setAttribute("for", String(safe[key]));
      } else if (key === "dataset" && safe[key] && typeof safe[key] === "object") {
        Object.keys(safe[key]).forEach(function (dataKey) {
          node.setAttribute("data-" + dataKey.replace(/[A-Z]/g, function (c) {
            return "-" + c.toLowerCase();
          }), String(safe[key][dataKey]));
        });
      } else if (key === "checked" || key === "disabled" || key === "selected") {
        node[key] = Boolean(safe[key]);
        if (safe[key]) node.setAttribute(key, "");
      } else if (key === "value" &&
                 (tag === "input" || tag === "textarea" || tag === "select" || tag === "option")) {
        node.value = String(safe[key]);
      } else {
        node.setAttribute(key, String(safe[key]));
      }
    });
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? doc.createTextNode(child) : child);
    });
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function actionButton(doc, action, label, kind) {
    return h(doc, "button", {
      type: "button",
      class: "btn" + (kind ? " " + kind : ""),
      dataset: { action: action },
      text: label
    }, []);
  }

  function dl(doc, entries) {
    var list = h(doc, "dl", { class: "review-block" }, []);
    entries.forEach(function (entry) {
      list.appendChild(h(doc, "dt", { text: entry[0] }, []));
      list.appendChild(h(doc, "dd", { text: entry[1] }, []));
    });
    return list;
  }

  function textInput(doc, id, value, extra) {
    var attrs = { id: id, value: value === null || value === undefined ? "" : value };
    if (extra) Object.keys(extra).forEach(function (key) { attrs[key] = extra[key]; });
    return h(doc, "input", attrs, []);
  }

  function isoNow() {
    try {
      return new Date().toISOString();
    } catch (err) {
      return "";
    }
  }

  function defaultEntry() {
    return {
      name: "",
      sender: { company: "", rep: "", bizNo: "", address: "", phone: "", email: "" },
      validDays: 30,
      taxMode: "EXCLUSIVE",
      memo: "",
      variableFlags: { memo: true, taxMode: true }
    };
  }

  function bindManualSection(doc, env) {
    var options = env || {};
    var root = {};
    Object.keys(IDS).forEach(function (key) { root[key] = doc.getElementById(IDS[key]); });
    if (!root.panel || !root.body) return null;

    if (root.panel) root.panel.hidden = true;

    var ui = {
      open: false,
      status: STATUS.DRAFT,
      entry: defaultEntry(),
      candidate: null,
      review: null,
      pending: false,
      approvalRequests: 0,
      trigger: null
    };

    function authState() {
      var state = typeof options.authState === "function" ? options.authState() : null;
      if (!state || typeof state !== "object") return { authenticated: false, privateStateReadable: false };
      return {
        authenticated: state.authenticated === true,
        privateStateReadable: state.privateStateReadable === true
      };
    }

    function signedIn() {
      var state = authState();
      return state.authenticated === true && state.privateStateReadable === true;
    }

    function announce(message) {
      if (root.status) root.status.textContent = message || "";
    }

    function messageFor(code) {
      return MESSAGES[code] || "처리하지 못했습니다. 다시 시도해 주세요.";
    }

    function persist() {
      if (!signedIn()) return false;
      if (!options.storage) return false;
      return writeManualDraft(options.storage, {
        schemaVersion: DRAFT_SCHEMA_VERSION,
        status: ui.status,
        entry: ui.entry,
        updatedAt: isoNow()
      });
    }

    function renderGate() {
      clear(root.body);
      root.body.appendChild(h(doc, "p", {
        class: "template-manage-note",
        text: "직접 만들기는 로그인한 계정에서만 사용할 수 있습니다. 로그인하면 회사 기본값을 입력해 새 견적서 후보를 준비할 수 있습니다."
      }, []));
      root.body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "msk-signin", "로그인", "primary")
      ]));
      announce("로그인이 필요합니다.");
    }

    function renderForm() {
      clear(root.body);
      var entry = ui.entry;
      var body = root.body;
      body.appendChild(h(doc, "p", {
        class: "template-manage-note",
        text: "항상 같은 회사 정보와 기본값을 입력합니다. 거래처·견적번호·작성일·품목은 견적마다 따로 입력하며 여기에 저장되지 않습니다."
      }, []));
      var form = h(doc, "div", { class: "fields" }, []);
      [["msk-name", "내 견적서 이름", entry.name],
       ["msk-company", "회사명", entry.sender.company],
       ["msk-rep", "대표자", entry.sender.rep],
       ["msk-bizno", "사업자번호", entry.sender.bizNo],
       ["msk-address", "주소", entry.sender.address],
       ["msk-phone", "연락처", entry.sender.phone],
       ["msk-email", "이메일", entry.sender.email]
      ].forEach(function (spec) {
        var label = h(doc, "label", { htmlFor: spec[0] }, [spec[1] + " "]);
        label.appendChild(textInput(doc, spec[0], spec[2], { maxlength: String(LIMITS.name) }));
        form.appendChild(label);
      });
      var validLabel = h(doc, "label", { htmlFor: "msk-valid-days" }, ["기본 유효기간(일) "]);
      validLabel.appendChild(textInput(doc, "msk-valid-days", String(entry.validDays), { inputmode: "numeric" }));
      form.appendChild(validLabel);
      var taxLabel = h(doc, "label", { htmlFor: "msk-tax-mode" }, ["기본 세금 방식 "]);
      var taxSelect = h(doc, "select", { id: "msk-tax-mode" }, []);
      TAX_MODES.forEach(function (mode) {
        var option = h(doc, "option", { value: mode, text: mode }, []);
        if (mode === entry.taxMode) option.selected = true;
        taxSelect.appendChild(option);
      });
      taxLabel.appendChild(taxSelect);
      form.appendChild(taxLabel);
      body.appendChild(form);

      var memoLabel = h(doc, "label", { htmlFor: "msk-memo" }, ["기본 비고 "]);
      memoLabel.appendChild(h(doc, "textarea", { id: "msk-memo", value: entry.memo }, []));
      body.appendChild(h(doc, "div", { class: "fields" }, [memoLabel]));

      var flags = h(doc, "div", { class: "fields" }, []);
      var memoFlag = h(doc, "label", {}, []);
      var memoBox = h(doc, "input", { id: "msk-flag-memo", type: "checkbox" }, []);
      memoBox.checked = entry.variableFlags.memo === true;
      memoFlag.appendChild(memoBox);
      memoFlag.appendChild(doc.createTextNode(" 건별 비고 입력 허용"));
      flags.appendChild(memoFlag);
      var taxFlag = h(doc, "label", {}, []);
      var taxBox = h(doc, "input", { id: "msk-flag-taxmode", type: "checkbox" }, []);
      taxBox.checked = entry.variableFlags.taxMode === true;
      taxFlag.appendChild(taxBox);
      taxFlag.appendChild(doc.createTextNode(" 건별 세금 방식 변경 허용"));
      flags.appendChild(taxFlag);
      body.appendChild(flags);

      body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "msk-save", "초안 저장"),
        actionButton(doc, "msk-review", "다음: 검토", "primary")
      ]));
      if (root.status && !root.status.textContent) announce("");
    }

    function renderReview() {
      clear(root.body);
      var review = ui.review;
      if (!review) { renderForm(); return; }
      var body = root.body;
      body.appendChild(h(doc, "h4", { text: "A. 출처" }, []));
      body.appendChild(dl(doc, [
        ["입력 방식", "직접 만들기 (사용자 입력)"],
        ["후보 이름", review.name],
        ["후보 상태", "승인 전 후보"],
        ["확인 필요", review.source.unknowns.join("; ") || "없음"]
      ]));
      body.appendChild(h(doc, "h4", { text: "B. 항상 다시 사용하는 값" }, []));
      body.appendChild(dl(doc, review.alwaysReusedOrDefault.map(function (row) {
        return [row.label, String(row.value === "" || row.value === null ? "(비어 있음)" : row.value)];
      })));
      body.appendChild(h(doc, "h4", { text: "C. 견적마다 바뀌는 값 (저장하지 않음)" }, []));
      body.appendChild(dl(doc, review.changesEachQuote.map(function (row) {
        return [row.label, row.required ? "필수 입력" : "선택 입력"];
      })));
      body.appendChild(h(doc, "h4", { text: "D. 자동 계산" }, []));
      body.appendChild(dl(doc, review.calculatedByCore.map(function (row) {
        return [row.key, row.authority];
      })));
      body.appendChild(h(doc, "p", {
        class: "template-manage-note",
        text: "출력 양식은 기본 견적서 양식을 사용합니다. 저장되는 것은 승인 전 후보이며, 아직 내 견적서로 사용할 수 없습니다."
      }, []));
      body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "msk-edit", "수정하러 가기", "soft"),
        actionButton(doc, "msk-request-approval", "승인 요청", "primary")
      ]));
      announce("검토 내용을 확인한 뒤 승인 요청을 할 수 있습니다.");
    }

    function renderApprovalResult(result) {
      clear(root.body);
      var body = root.body;
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "승인 요청 연결 전" }, []));
      body.appendChild(dl(doc, [
        ["후보 이름", ui.review ? ui.review.name : ""],
        ["현재 상태", "승인 전 후보 · 사용 불가"],
        ["결과", result && result.code ? result.code : "approval_endpoint_unavailable"],
        ["필요 작업", BACKEND_PREREQUISITE]
      ]));
      body.appendChild(h(doc, "p", {
        class: "template-manage-note",
        text: "초안은 이 브라우저에만 보관되며 승인된 내 견적서로 저장되지 않았습니다. 승인 서버가 연결되기 전에는 어떤 화면에서도 승인 완료로 표시되지 않습니다."
      }, []));
      body.appendChild(h(doc, "div", { class: "button-row" }, [
        actionButton(doc, "msk-edit", "수정하러 가기", "soft"),
        actionButton(doc, "msk-discard", "초안 삭제", "soft")
      ]));
      announce(APPROVAL_NOT_CONNECTED_MESSAGE);
    }

    function render() {
      if (!signedIn()) { renderGate(); return; }
      if (ui.status === STATUS.REVIEW && ui.review) { renderReview(); return; }
      if (ui.status === STATUS.APPROVAL_NOT_CONNECTED) { renderApprovalResult(null); return; }
      renderForm();
    }

    function readForm() {
      var get = function (id) {
        var node = doc.getElementById(id);
        return node && node.value !== undefined ? String(node.value) : "";
      };
      var checked = function (id) {
        var node = doc.getElementById(id);
        return Boolean(node && node.checked);
      };
      return {
        name: get("msk-name"),
        sender: {
          company: get("msk-company"),
          rep: get("msk-rep"),
          bizNo: get("msk-bizno"),
          address: get("msk-address"),
          phone: get("msk-phone"),
          email: get("msk-email")
        },
        validDays: get("msk-valid-days"),
        taxMode: get("msk-tax-mode"),
        memo: get("msk-memo"),
        variableFlags: { memo: checked("msk-flag-memo"), taxMode: checked("msk-flag-taxmode") }
      };
    }

    function goReview() {
      var normalized = normalizeManualEntry(readForm());
      if (!normalized.ok) {
        announce(messageFor(normalized.code));
        return;
      }
      ui.entry = normalized.entry;
      var built = buildManualCandidate(ui.entry, { now: isoNow() });
      if (!built.ok || !built.candidate) {
        announce(messageFor(built.code));
        return;
      }
      ui.candidate = built.candidate;
      ui.review = built.review;
      ui.status = STATUS.REVIEW;
      persist();
      render();
    }

    function submitApprovalRequest() {
      if (ui.pending) return;
      ui.pending = true;
      try {
        ui.approvalRequests += 1;
        var result = requestApproval(ui.candidate, { now: isoNow() });
        ui.status = result.status;
        persist();
        renderApprovalResult(result);
      } finally {
        ui.pending = false;
      }
    }

    function discardDraft() {
      clearManualDraft(options.storage);
      ui.status = STATUS.DRAFT;
      ui.candidate = null;
      ui.review = null;
      ui.entry = defaultEntry();
      announce("초안을 삭제했습니다. 저장된 후보는 없습니다.");
      render();
    }

    /* 로그인 진입은 기존 계정 버튼을 다시 누르는 것뿐이다. 새 인증 경로를 만들지 않는다. */
    function openSignIn() {
      if (typeof options.openSignIn === "function") { options.openSignIn(); return; }
      var button = doc.getElementById("padiemAccountButton");
      if (button && typeof button.click === "function") button.click();
    }

    function handleAction(action) {
      if (action === "msk-signin") {
        openSignIn();
        return;
      }
      if (action === "msk-save") {
        var normalized = normalizeManualEntry(readForm());
        if (!normalized.ok) { announce(messageFor(normalized.code)); return; }
        ui.entry = normalized.entry;
        ui.status = STATUS.DRAFT;
        if (persist()) announce("초안을 이 브라우저에 저장했습니다. 승인된 내 견적서는 아닙니다.");
        else announce("초안을 저장하지 못했습니다. 로그인 상태를 확인해 주세요.");
        return;
      }
      if (action === "msk-review") { goReview(); return; }
      if (action === "msk-edit") {
        ui.status = STATUS.DRAFT;
        render();
        return;
      }
      if (action === "msk-request-approval") { submitApprovalRequest(); return; }
      if (action === "msk-discard") { discardDraft(); return; }
    }

    function onClick(event) {
      var target = event && event.target && typeof event.target.closest === "function"
        ? event.target.closest("[data-action]")
        : null;
      if (!target) return;
      handleAction(target.getAttribute("data-action"));
    }

    if (root.body) root.body.addEventListener("click", onClick);
    if (root.close) {
      root.close.addEventListener("click", function () { api.close(); });
    }

    var api = {
      ids: IDS,
      open: function (trigger) {
        ui.trigger = trigger || null;
        ui.open = true;
        if (root.panel) root.panel.hidden = false;
        var stored = signedIn() ? readManualDraft(options.storage) : null;
        if (stored) {
          ui.entry = stored.entry;
          ui.status = STATUS.DRAFT;
          ui.candidate = null;
          ui.review = null;
        }
        render();
        if (root.title && typeof root.title.focus === "function") root.title.focus();
        return true;
      },
      close: function () {
        ui.open = false;
        if (root.panel) root.panel.hidden = true;
        clear(root.body);
        announce("");
        if (ui.trigger && typeof ui.trigger.focus === "function") ui.trigger.focus();
        ui.trigger = null;
        return true;
      },
      refresh: function () { if (ui.open) render(); return true; },
      getState: function () {
        return {
          open: ui.open,
          status: ui.status,
          entry: ui.entry,
          candidate: ui.candidate,
          review: ui.review,
          approvalRequests: ui.approvalRequests,
          signedIn: signedIn()
        };
      },
      actions: {
        handleAction: handleAction,
        onClick: onClick
      }
    };

    return api;
  }

  return {
    MANUAL_DRAFT_STORAGE_KEY: MANUAL_DRAFT_STORAGE_KEY,
    DRAFT_SCHEMA_VERSION: DRAFT_SCHEMA_VERSION,
    MANUAL_SOURCE_KIND: MANUAL_SOURCE_KIND,
    MANUAL_EXTRACTION_SOURCE_KIND: MANUAL_EXTRACTION_SOURCE_KIND,
    MANUAL_SOURCE_REF: MANUAL_SOURCE_REF,
    APPROVAL_ENDPOINT: APPROVAL_ENDPOINT,
    APPROVAL_NOT_CONNECTED_MESSAGE: APPROVAL_NOT_CONNECTED_MESSAGE,
    BACKEND_PREREQUISITE: BACKEND_PREREQUISITE,
    STATUS: STATUS,
    TAX_MODES: TAX_MODES.slice(),
    LIMITS: LIMITS,
    MAX_DRAFT_CHARS: MAX_DRAFT_CHARS,
    IDS: IDS,
    MESSAGES: MESSAGES,
    sanitizeText: sanitizeText,
    normalizeManualEntry: normalizeManualEntry,
    buildManualCandidate: buildManualCandidate,
    approvalRequestState: approvalRequestState,
    requestApproval: requestApproval,
    readManualDraft: readManualDraft,
    writeManualDraft: writeManualDraft,
    clearManualDraft: clearManualDraft,
    bindManualSection: bindManualSection
  };
});
