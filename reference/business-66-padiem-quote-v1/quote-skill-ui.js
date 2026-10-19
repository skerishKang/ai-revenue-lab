/* B66 · Quote Beta — quote-skill-ui.js
   "내 견적서" 사용자-facing UI 로직 + 바인딩.

   원칙:
   - DOM API(createElement/textContent)로만 렌더한다. innerHTML 을 쓰지 않아
     주입된 문자열이 마크업으로 실행될 수 없고, Node 스텁 DOM로 전부 테스트된다.
   - 이미지 등록 분석은 same-origin /api/v1/quote/intake 경로만 사용한다.
     provider/model/credential 선택은 서버 authority에 남고 브라우저에는 노출하지 않는다.
   - 저장은 env.storage 를 통해서만 Session.commit 경로로 일어나고,
     preview/correction 단계는 저장소를 건드리지 않는다.
   - 과장 문구를 쓰지 않는다. 자동 layout 분석은 없다고 명시한다.

   (브라우저/Node 양쪽에서 실행. Node 에서는 doc 스텁을 주입한다) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(
      require("./quote-skill.js"),
      require("./quote-skill-store.js"),
      require("./quote-registration-session.js"),
      require("./quote-template-store.js"),
      require("./file-intake.js")
    );
  } else {
    root.SavedQuoteSkillUi = factory(
      root.SavedQuoteSkill,
      root.SavedQuoteSkillStore,
      root.QuoteRegistrationSession,
      root.QuoteTemplateStore,
      root.B66FileIntake
    );
  }
})(typeof self !== "undefined" ? self : this, function (Skill, SkillStore, Session, TemplateStore, FileIntake) {
  "use strict";

  if (!Skill) throw new Error("SavedQuoteSkill is required");
  if (!SkillStore) throw new Error("SavedQuoteSkillStore is required");
  if (!Session) throw new Error("QuoteRegistrationSession is required");
  if (!TemplateStore) throw new Error("QuoteTemplateStore is required");
  if (!FileIntake) throw new Error("B66FileIntake is required");

  var IDS = {
    section: "skillSection",
    select: "skillSelect",
    status: "skillStatus",
    emptyState: "skillEmptyState",
    register: "skillRegister",
    write: "skillWrite",
    manageToggle: "skillManageToggle",
    managePanel: "skillManagePanel",
    list: "skillList",
    wizard: "skillWizardPanel",
    wizardTitle: "skillWizardTitle",
    wizardStatus: "skillWizardStatus",
    wizardBody: "skillWizardBody",
    wizardCancel: "skillWizardCancel",
    file: "skillRegisterFile"
  };

  var BUILTIN_OPTION_VALUE = "";
  var BUILTIN_OPTION_LABEL = "기본 견적서";

  var STEP_TITLES = {
    1: "1. 견적서 선택",
    2: "2. 회사정보 / 업무값 확인",
    3: "3. 견적서 모양 확인",
    4: "4. 필요한 부분 수정",
    5: "5. 최종 확인",
    6: "6. 내 견적서 저장"
  };

  /* ── DOM 빌더 (innerHTML 미사용) ── */

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
      } else if (key === "value" && (tag === "input" || tag === "textarea" || tag === "select" || tag === "option")) {
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

  function fieldRow(doc, id, label, control) {
    var labelNode = h(doc, "label", { htmlFor: id }, [label + " "]);
    labelNode.appendChild(control);
    var wrap = h(doc, "div", { class: "fields" }, [labelNode]);
    return wrap;
  }

  function textInput(doc, id, value, extra) {
    var attrs = { id: id, value: value === null || value === undefined ? "" : value };
    if (extra) Object.keys(extra).forEach(function (k) { attrs[k] = extra[k]; });
    return h(doc, "input", attrs, []);
  }

  function actionButton(doc, action, label, kind) {
    return h(doc, "button", {
      type: "button",
      class: "btn" + (kind ? " " + kind : ""),
      dataset: { action: action },
      text: label
    }, []);
  }

  /* ── 순수 빌더 ── */

  function buildSkillOptions(skills, activeSkillId, defaultSkillId) {
    var options = [{
      value: BUILTIN_OPTION_VALUE,
      label: BUILTIN_OPTION_LABEL,
      selected: !activeSkillId,
      isDefault: !defaultSkillId
    }];
    (skills || []).forEach(function (skill) {
      options.push({
        value: skill.id,
        label: skill.name + (skill.id === defaultSkillId ? " (기본)" : ""),
        selected: skill.id === activeSkillId,
        isDefault: skill.id === defaultSkillId
      });
    });
    return options;
  }

  function buildSkillRows(skills, state) {
    var activeId = state && state.activeSkillId;
    var defaultId = state && state.defaultSkillId;
    var renamingId = state && state.renamingSkillId;
    return (skills || []).map(function (skill) {
      return {
        id: skill.id,
        name: skill.name,
        isActive: skill.id === activeId,
        isDefault: skill.id === defaultId,
        isRenaming: skill.id === renamingId,
        canUse: true,
        canRename: true,
        canDelete: true,
        canSetDefault: skill.id !== defaultId
      };
    });
  }

  function formValuesFromSkill(skill) {
    if (!skill) return null;
    return {
      sender: {
        company: skill.fixedDefaults.sender.company,
        rep: skill.fixedDefaults.sender.rep,
        contactPerson: skill.fixedDefaults.sender.contactPerson || "",
        bizNo: skill.fixedDefaults.sender.bizNo,
        address: skill.fixedDefaults.sender.address,
        phone: skill.fixedDefaults.sender.phone,
        email: skill.fixedDefaults.sender.email
      },
      validDays: skill.fixedDefaults.validDays,
      taxMode: skill.fixedDefaults.taxMode,
      memo: skill.fixedDefaults.memo,
      templateId: skill.internalTemplate.id,
      templateFingerprint: skill.internalTemplate.fingerprint
    };
  }

  function wizardStepForSession(session) {
    if (!session) return 1;
    switch (session.status) {
      case Session.STATUS_TEMPLATE_REVIEW: return 3;
      case Session.STATUS_TEMPLATE_APPROVED: return 5;
      case Session.STATUS_SKILL_REVIEW: return 5;
      case Session.STATUS_SKILL_APPROVED: return 6;
      case Session.STATUS_COMMITTED: return 6;
      default: return 1;
    }
  }

  var LIVE_INTAKE_ENDPOINT = "/api/v1/quote/intake";

  function extractionKindForCategory(category) {
    return category === "image" ? "image" : "native_document";
  }

  function bytesToBase64(buffer) {
    var bytes = new Uint8Array(buffer);
    var chunk = 0x8000;
    var binary = "";
    for (var offset = 0; offset < bytes.length; offset += chunk) {
      var slice = bytes.subarray(offset, Math.min(offset + chunk, bytes.length));
      binary += String.fromCharCode.apply(null, Array.from(slice));
    }
    if (typeof btoa === "function") return btoa(binary);
    if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
    throw new Error("base64_unavailable");
  }

  async function analyzeFile(file, fileMeta, fetchFn) {
    if (!fileMeta || ["image", "native_document"].indexOf(fileMeta.category) === -1) {
      return { ok: false, code: "manual_only" };
    }
    if (!file || typeof file.arrayBuffer !== "function") return { ok: false, code: "file_read_unavailable" };
    if (typeof fetchFn !== "function") return { ok: false, code: "analysis_service_unavailable" };

    try {
      var bytes = await file.arrayBuffer();
      if (!bytes || bytes.byteLength !== fileMeta.byteSize) {
        return { ok: false, code: "file_size_changed" };
      }
      var response = await fetchFn(LIVE_INTAKE_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({
          name: fileMeta.name,
          media_type: fileMeta.mediaType,
          base64: bytesToBase64(bytes)
        })
      });
      var payload = await response.json();
      if (!response.ok || !payload || payload.ok !== true || !payload.result ||
          !payload.result.extraction || typeof payload.result.extraction !== "object") {
        var code = payload && payload.error && typeof payload.error.code === "string"
          ? payload.error.code
          : "analysis_failed";
        return { ok: false, code: code };
      }
      return {
        ok: true,
        extraction: payload.result.extraction,
        unknowns: Array.isArray(payload.result.unknowns) ? payload.result.unknowns.slice() : []
      };
    } catch (err) {
      return { ok: false, code: "analysis_service_unavailable" };
    }
  }

  async function analyzeImageFile(file, fileMeta, fetchFn) {
    if (!fileMeta || fileMeta.category !== "image") return { ok: false, code: "manual_only" };
    return analyzeFile(file, fileMeta, fetchFn);
  }

  function factsFromExtraction(extraction) {
    if (!extraction || typeof extraction !== "object") return null;
    var sender = extraction.sender && typeof extraction.sender === "object" ? extraction.sender : {};
    var quote = extraction.quote && typeof extraction.quote === "object" ? extraction.quote : {};
    var tax = extraction.tax && typeof extraction.tax === "object" ? extraction.tax : {};
    var company = sender.company || "";
    return {
      sender: {
        company: sender.company || "",
        rep: sender.rep || "",
        bizNo: sender.bizNo || "",
        address: sender.address || "",
        phone: sender.phone || "",
        email: sender.email || ""
      },
      validDays: quote.validDays || "",
      taxMode: tax.mode || "",
      memo: extraction.memo || "",
      skillName: company ? company + " 견적서" : "우리회사 일반 견적서"
    };
  }

  function registrationModelOutput(extraction, kind, filename) {
    if (extraction && typeof extraction === "object") return JSON.parse(JSON.stringify(extraction));
    return {
      source: { kind: kind, filename: filename },
      sender: { company: null, rep: null, bizNo: null, address: null, phone: null, email: null },
      recipient: { company: null, person: null, address: null, email: null },
      quote: { quoteNo: null, issueDate: null, validDays: null },
      items: [],
      tax: { mode: null },
      memo: null,
      evidence: [],
      warnings: []
    };
  }

  /* ── 바인딩 ── */

  function bindSkillSection(doc, env) {
    var root = {};
    Object.keys(IDS).forEach(function (key) {
      root[key] = doc.getElementById(IDS[key]);
    });
    if (!root.section || !root.select || !root.wizardBody) return null;
    /* Initial collapsed state mirrors index.html hidden attributes. */
    if (root.wizard) root.wizard.hidden = true;
    if (root.managePanel) root.managePanel.hidden = true;

    var ui = {
      session: null,
      step: 1,
      fileMeta: null,
      facts: null,
      extraction: null,
      analysisStatus: "idle",
      analysisError: null,
      analysisToken: 0,
      trigger: null,
      renamingSkillId: null,
      activeSkillId: null
    };

    function announce(message) {
      if (root.wizardStatus) root.wizardStatus.textContent = message || "";
      if (root.status) root.status.textContent = message || "";
    }

    function readStore() {
      return SkillStore.readStore(env.storage);
    }

    function allSkills() {
      return SkillStore.listSkills(readStore());
    }

    function refreshSkills() {
      var store = readStore();
      var skills = SkillStore.listSkills(store);
      var defaultSkill = SkillStore.defaultSkill(store);
      var defaultId = defaultSkill ? defaultSkill.id : null;
      if (ui.activeSkillId && !SkillStore.getSkill(store, ui.activeSkillId)) {
        ui.activeSkillId = null;
      }
      clear(root.select);
      buildSkillOptions(skills, ui.activeSkillId, defaultId).forEach(function (option) {
        var node = h(doc, "option", { value: option.value, text: option.label }, []);
        if (option.selected) node.selected = true;
        root.select.appendChild(node);
      });
      if (root.emptyState) root.emptyState.hidden = skills.length > 0;
      renderManage(skills, defaultId);
      return { skills: skills, defaultId: defaultId };
    }

    function renderManage(skills, defaultId) {
      clear(root.list);
      var rows = buildSkillRows(skills, { activeSkillId: ui.activeSkillId, defaultSkillId: defaultId, renamingSkillId: ui.renamingSkillId });
      if (rows.length === 0) {
        root.list.appendChild(h(doc, "p", { class: "template-manage-note", text: "저장된 내 견적서가 없습니다." }, []));
        return;
      }
      rows.forEach(function (row) {
        var item = h(doc, "div", { class: "template-row", role: "listitem" }, []);
        var main = h(doc, "div", { class: "template-row-main" }, []);
        if (row.isRenaming) {
          var input = textInput(doc, "skill-rename-" + row.id, row.name, { "aria-label": "내 견적서 이름" });
          input.setAttribute("data-role", "rename-input");
          main.appendChild(input);
          main.appendChild(actionButton(doc, "skill-rename-save:" + row.id, "저장"));
          main.appendChild(actionButton(doc, "skill-rename-cancel", "취소", "soft"));
        } else {
          main.appendChild(h(doc, "strong", { text: row.name + (row.isDefault ? " (기본)" : "") }, []));
        }
        var actions = h(doc, "div", { class: "template-row-actions" }, []);
        if (!row.isRenaming) {
          actions.appendChild(actionButton(doc, "skill-use:" + row.id, "이 견적서로 작성"));
          actions.appendChild(actionButton(doc, "skill-rename:" + row.id, "이름 변경", "soft"));
          if (row.canSetDefault) actions.appendChild(actionButton(doc, "skill-default:" + row.id, "기본으로 설정", "soft"));
          else actions.appendChild(actionButton(doc, "skill-default-clear", "기본 해제", "soft"));
          actions.appendChild(actionButton(doc, "skill-delete:" + row.id, "삭제", "soft"));
        }
        item.appendChild(main);
        item.appendChild(actions);
        root.list.appendChild(item);
      });
    }

    function setStep(step) {
      ui.step = step;
      if (root.wizardTitle) {
        root.wizardTitle.textContent = STEP_TITLES[step] || "내가 쓰던 견적서 등록";
        if (typeof root.wizardTitle.focus === "function") root.wizardTitle.focus();
      }
    }

    function openWizard(trigger) {
      ui.trigger = trigger || null;
      ui.session = null;
      ui.fileMeta = null;
      ui.facts = null;
      ui.extraction = null;
      ui.analysisStatus = "idle";
      ui.analysisError = null;
      ui.analysisToken += 1;
      root.wizard.hidden = false;
      renderStep1();
    }

    function closeWizard(message) {
      ui.analysisToken += 1;
      ui.session = null;
      ui.extraction = null;
      root.wizard.hidden = true;
      clear(root.wizardBody);
      env.renderMain();
      if (message) env.toast(message);
      if (ui.trigger && typeof ui.trigger.focus === "function") ui.trigger.focus();
      ui.trigger = null;
    }

    function readFactsForm() {
      var get = function (id) {
        var node = doc.getElementById(id);
        return node ? String(node.value !== undefined ? node.value : "") : "";
      };
      return {
        sender: {
          company: get("wiz-sender-company"),
          rep: get("wiz-sender-rep"),
          bizNo: get("wiz-sender-bizno"),
          address: get("wiz-sender-address"),
          phone: get("wiz-sender-phone"),
          email: get("wiz-sender-email")
        },
        validDays: get("wiz-valid-days"),
        taxMode: get("wiz-tax-mode"),
        memo: get("wiz-memo"),
        skillName: get("wiz-skill-name")
      };
    }

    function readLayoutForm() {
      var get = function (id) {
        var node = doc.getElementById(id);
        return node ? String(node.value !== undefined ? node.value : "") : "";
      };
      var checked = function (id) {
        var node = doc.getElementById(id);
        return Boolean(node && node.checked);
      };
      var content = JSON.parse(JSON.stringify(ui.session.templateCandidate.content));
      content.title.text = get("wiz-tpl-title");
      var sections = ["title", "meta", "parties", "items", "totals", "memo", "mark"].filter(function (key) {
        return checked("wiz-section-" + key);
      });
      content.sections = sections.length > 0 ? sections : ["title", "meta", "parties", "items", "totals", "memo", "mark"];
      content.items.columns = [0, 1, 2, 3].map(function (i) {
        return {
          key: get("wiz-col-" + i + "-key"),
          label: get("wiz-col-" + i + "-label"),
          width: get("wiz-col-" + i + "-width"),
          align: get("wiz-col-" + i + "-align")
        };
      });
      content.totals.supplyLabel = get("wiz-supply-label");
      content.totals.grandLabel = get("wiz-grand-label");
      content.page.size = get("wiz-page-size");
      content.page.orientation = get("wiz-page-orientation");
      content.page.margin = get("wiz-page-margin");
      content.style.accent = get("wiz-accent");
      content.style.titleRule = get("wiz-title-rule");
      content.style.headerAlignment = get("wiz-header-align");
      content.style.metaAlignment = get("wiz-meta-align");
      content.style.numericAlignment = get("wiz-numeric-align");
      content.style.totalsWidth = get("wiz-totals-width");
      content.items.emptyNameText = get("wiz-empty-name");
      content.memo.emptyText = get("wiz-memo-empty");
      content.mark.text = get("wiz-mark");
      return {
        name: get("wiz-tpl-name"),
        content: content
      };
    }

    function dl(doc, entries) {
      var list = h(doc, "dl", { class: "review-block" }, []);
      entries.forEach(function (entry) {
        list.appendChild(h(doc, "dt", { text: entry[0] }, []));
        list.appendChild(h(doc, "dd", { text: entry[1] }, []));
      });
      return list;
    }

    function renderStep1() {
      setStep(1);
      clear(root.wizardBody);
      var body = root.wizardBody;
      body.appendChild(h(doc, "p", { text: "기존에 사용하던 견적서 파일을 선택하세요. 지원 파일은 분석을 위해 서버로 일시 전송되며 원본 바이트는 저장하지 않습니다." }, []));
      if (ui.fileMeta) {
        body.appendChild(dl(doc, [
          ["파일명", ui.fileMeta.name],
          ["파일 형식", ui.fileMeta.label],
          ["크기", ui.fileMeta.displaySize]
        ]));
        var sourceLabel = ui.fileMeta.category === "image" ? "이미지" : "문서";
        if (ui.analysisStatus === "loading") {
          body.appendChild(h(doc, "p", { class: "template-manage-note", text: sourceLabel + "에서 견적 내용을 분석하고 있습니다…" }, []));
          body.appendChild(actionButton(doc, "wiz-step2", "기다리지 않고 수동으로 계속", "soft"));
        } else if (ui.analysisStatus === "ready") {
          body.appendChild(h(doc, "p", { class: "template-manage-note", text: sourceLabel + " 내용 분석이 끝났습니다. 다음 단계에서 회사 기본값을 확인·수정하세요." }, []));
          body.appendChild(actionButton(doc, "wiz-step2", "다음: 회사정보 확인", "primary"));
        } else if (ui.analysisStatus === "error") {
          body.appendChild(h(doc, "p", { class: "template-manage-note", text: "자동 분석을 완료하지 못했습니다. 원본과 비교해 직접 확인하며 등록을 계속할 수 있습니다." }, []));
          body.appendChild(actionButton(doc, "wiz-step2", "수동으로 계속", "primary"));
        } else if (ui.analysisStatus === "manual") {
          body.appendChild(h(doc, "p", { class: "template-manage-note", text: "이 파일은 직접 확인 방식으로 등록합니다." }, []));
          body.appendChild(actionButton(doc, "wiz-step2", "다음: 회사정보 확인", "primary"));
        }
      } else {
        body.appendChild(actionButton(doc, "wiz-pick-file", "파일 선택", "primary"));
      }
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "JPG·PNG·WebP(4MB 이하)와 PDF·DOCX·PPTX·XLSX·HWPX(2MB 이하)는 자동 분석을 시도합니다. 문서 파서가 준비되지 않은 환경이나 분석 실패 시 수동 확인으로 계속할 수 있습니다." }, []));
    }

    function renderStep2() {
      setStep(2);
      clear(root.wizardBody);
      var body = root.wizardBody;
      var draft = env.getDraftSnapshot ? env.getDraftSnapshot() : null;
      var sender = (draft && draft.sender) || {};
      var facts = ui.facts || {};
      var senderFacts = facts.sender || {};
      var val = function (fromFacts, fromDraft, fallback) {
        if (fromFacts !== undefined && fromFacts !== null && fromFacts !== "") return fromFacts;
        if (fromDraft !== undefined && fromDraft !== null && fromDraft !== "") return fromDraft;
        return fallback || "";
      };
      body.appendChild(h(doc, "h4", { text: "항상 사용하는 정보 (검토 후 기본값으로 저장)" }, []));
      var form = h(doc, "div", { class: "fields" }, []);
      [["wiz-sender-company", "회사명", val(senderFacts.company, sender.company)],
       ["wiz-sender-rep", "대표자", val(senderFacts.rep, sender.rep)],
       ["wiz-sender-bizno", "사업자번호", val(senderFacts.bizNo, sender.bizNo)],
       ["wiz-sender-address", "주소", val(senderFacts.address, sender.address)],
       ["wiz-sender-phone", "연락처", val(senderFacts.phone, sender.phone)],
       ["wiz-sender-email", "이메일", val(senderFacts.email, sender.email)]
      ].forEach(function (spec) {
        var label = h(doc, "label", { htmlFor: spec[0] }, [spec[1] + " "]);
        label.appendChild(textInput(doc, spec[0], spec[2], {}));
        form.appendChild(label);
      });
      body.appendChild(form);
      var row2 = h(doc, "div", { class: "fields" }, []);
      var validLabel = h(doc, "label", { htmlFor: "wiz-valid-days" }, ["기본 유효기간(일) "]);
      var validDays = val(facts.validDays, draft && draft.meta && draft.meta.validDays, "30");
      validLabel.appendChild(textInput(doc, "wiz-valid-days", validDays, { inputmode: "numeric" }));
      row2.appendChild(validLabel);
      var taxLabel = h(doc, "label", { htmlFor: "wiz-tax-mode" }, ["기본 세금 방식 "]);
      var taxSelect = h(doc, "select", { id: "wiz-tax-mode" }, []);
      var taxMode = val(facts.taxMode, draft && draft.tax && draft.tax.mode, "EXCLUSIVE");
      ["EXCLUSIVE", "INCLUSIVE", "EXEMPT"].forEach(function (mode) {
        var option = h(doc, "option", { value: mode, text: mode }, []);
        if (mode === taxMode) option.selected = true;
        taxSelect.appendChild(option);
      });
      taxLabel.appendChild(taxSelect);
      row2.appendChild(taxLabel);
      body.appendChild(row2);
      var memoLabel = h(doc, "label", { htmlFor: "wiz-memo" }, ["기본 비고 "]);
      memoLabel.appendChild(h(doc, "textarea", { id: "wiz-memo", value: val(facts.memo, draft && draft.memo, "") }, []));
      body.appendChild(h(doc, "div", { class: "fields" }, [memoLabel]));
      var nameLabel = h(doc, "label", { htmlFor: "wiz-skill-name" }, ["내 견적서 이름 "]);
      nameLabel.appendChild(textInput(doc, "wiz-skill-name", facts.skillName || "우리회사 일반 견적서", {}));
      body.appendChild(h(doc, "div", { class: "fields" }, [nameLabel]));
      body.appendChild(h(doc, "h4", { text: "견적마다 바뀌는 정보 (저장하지 않음)" }, []));
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "거래처·견적번호·작성일·품목·수량·단가는 매번 새로 입력합니다." }, []));
      body.appendChild(h(doc, "h4", { text: "자동 계산 항목" }, []));
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "품목별 금액·공급가액·부가세·총액·유효기한은 견적 작성 시 자동으로 계산됩니다." }, []));
      body.appendChild(actionButton(doc, "wiz-facts-next", "다음: 모양 확인", "primary"));
    }

    function renderStep3() {
      setStep(ui.session && ui.session.status === Session.STATUS_TEMPLATE_REVIEW ? 3 : 4);
      clear(root.wizardBody);
      var body = root.wizardBody;
      var review = ui.session.templateReview;
      var content = ui.session.templateCandidate.content;
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "기본 견적서 초안입니다. 원본 모양을 자동으로 분석하지 않으므로 비교해 수정해 주세요." }, []));
      var nameLabel = h(doc, "label", { htmlFor: "wiz-tpl-name" }, ["양식 이름 "]);
      nameLabel.appendChild(textInput(doc, "wiz-tpl-name", ui.session.templateCandidate.name, {}));
      body.appendChild(h(doc, "div", { class: "fields" }, [nameLabel]));
      var titleLabel = h(doc, "label", { htmlFor: "wiz-tpl-title" }, ["견적서 제목 "]);
      titleLabel.appendChild(textInput(doc, "wiz-tpl-title", content.title.text, {}));
      body.appendChild(h(doc, "div", { class: "fields" }, [titleLabel]));
      body.appendChild(h(doc, "h4", { text: "표시할 섹션" }, []));
      var sectionsBox = h(doc, "div", { class: "fields" }, []);
      ["title", "meta", "parties", "items", "totals", "memo", "mark"].forEach(function (key) {
        var label = h(doc, "label", {}, []);
        var box = h(doc, "input", { id: "wiz-section-" + key, type: "checkbox" }, []);
        if (content.sections.indexOf(key) !== -1) box.checked = true;
        label.appendChild(box);
        label.appendChild(doc.createTextNode(" " + key));
        sectionsBox.appendChild(label);
      });
      body.appendChild(sectionsBox);
      body.appendChild(h(doc, "h4", { text: "품목표 열 (순서·이름·너비·정렬)" }, []));
      var columns = (review && review.columns) || [];
      columns.forEach(function (column, i) {
        var row = h(doc, "div", { class: "fields" }, []);
        var keyLabel = h(doc, "label", { htmlFor: "wiz-col-" + i + "-key" }, ["열" + (i + 1) + " 항목 "]);
        var keySelect = h(doc, "select", { id: "wiz-col-" + i + "-key" }, []);
        ["name", "qty", "unitPrice", "amount"].forEach(function (key) {
          var option = h(doc, "option", { value: key, text: key }, []);
          if (key === column.key) option.selected = true;
          keySelect.appendChild(option);
        });
        keyLabel.appendChild(keySelect);
        row.appendChild(keyLabel);
        var labelLabel = h(doc, "label", { htmlFor: "wiz-col-" + i + "-label" }, ["이름 "]);
        labelLabel.appendChild(textInput(doc, "wiz-col-" + i + "-label", column.label, {}));
        row.appendChild(labelLabel);
        var widthLabel = h(doc, "label", { htmlFor: "wiz-col-" + i + "-width" }, ["너비 "]);
        widthLabel.appendChild(textInput(doc, "wiz-col-" + i + "-width", column.width, { placeholder: "예: 42%" }));
        row.appendChild(widthLabel);
        var alignLabel = h(doc, "label", { htmlFor: "wiz-col-" + i + "-align" }, ["정렬 "]);
        var alignSelect = h(doc, "select", { id: "wiz-col-" + i + "-align" }, []);
        ["left", "right", "center"].forEach(function (align) {
          var option = h(doc, "option", { value: align, text: align }, []);
          if (align === column.align) option.selected = true;
          alignSelect.appendChild(option);
        });
        alignLabel.appendChild(alignSelect);
        row.appendChild(alignLabel);
        body.appendChild(row);
      });
      body.appendChild(h(doc, "h4", { text: "합계 라벨·용지·스타일" }, []));
      var misc = h(doc, "div", { class: "fields" }, []);
      [["wiz-supply-label", "공급가액 라벨", content.totals.supplyLabel],
       ["wiz-grand-label", "총액 라벨", content.totals.grandLabel],
       ["wiz-page-margin", "여백", content.page.margin],
       ["wiz-accent", "강조색", content.style.accent],
       ["wiz-title-rule", "제목 규칙", content.style.titleRule],
       ["wiz-totals-width", "합계 영역 폭", content.style.totalsWidth],
       ["wiz-empty-name", "빈 품목 문구", content.items.emptyNameText],
       ["wiz-memo-empty", "빈 비고 문구", content.memo.emptyText],
       ["wiz-mark", "표시 문구", content.mark.text]
      ].forEach(function (spec) {
        var label = h(doc, "label", { htmlFor: spec[0] }, [spec[1] + " "]);
        label.appendChild(textInput(doc, spec[0], spec[2], {}));
        misc.appendChild(label);
      });
      var sizeLabel = h(doc, "label", { htmlFor: "wiz-page-size" }, ["용지 크기 "]);
      var sizeSelect = h(doc, "select", { id: "wiz-page-size" }, []);
      ["A4", "A5", "Legal", "Letter"].forEach(function (size) {
        var option = h(doc, "option", { value: size, text: size }, []);
        if (size === content.page.size) option.selected = true;
        sizeSelect.appendChild(option);
      });
      sizeLabel.appendChild(sizeSelect);
      misc.appendChild(sizeLabel);
      var oriLabel = h(doc, "label", { htmlFor: "wiz-page-orientation" }, ["방향 "]);
      var oriSelect = h(doc, "select", { id: "wiz-page-orientation" }, []);
      ["portrait", "landscape"].forEach(function (ori) {
        var option = h(doc, "option", { value: ori, text: ori }, []);
        if (ori === content.page.orientation) option.selected = true;
        oriSelect.appendChild(option);
      });
      oriLabel.appendChild(oriSelect);
      misc.appendChild(oriLabel);
      [["wiz-header-align", "머리글 정렬", content.style.headerAlignment, ["flex-start", "center", "flex-end", "space-between", "space-around"]],
       ["wiz-meta-align", "정보 정렬", content.style.metaAlignment, ["left", "right", "center"]],
       ["wiz-numeric-align", "숫자 정렬", content.style.numericAlignment, ["left", "right", "center"]]
      ].forEach(function (spec) {
        var label = h(doc, "label", { htmlFor: spec[0] }, [spec[1] + " "]);
        var select = h(doc, "select", { id: spec[0] }, []);
        spec[3].forEach(function (value) {
          var option = h(doc, "option", { value: value, text: value }, []);
          if (value === spec[2]) option.selected = true;
          select.appendChild(option);
        });
        label.appendChild(select);
        misc.appendChild(label);
      });
      body.appendChild(misc);
      body.appendChild(h(doc, "p", { class: "template-manage-note", text: "로고/도장 자동 배치는 현재 지원 준비 중입니다." }, []));
      var actions = h(doc, "div", { class: "button-row" }, []);
      actions.appendChild(actionButton(doc, "wiz-preview-update", "미리보기 업데이트"));
      actions.appendChild(actionButton(doc, "wiz-use-layout", "이 모양 사용", "primary"));
      body.appendChild(actions);
    }

    function renderStep5() {
      setStep(5);
      clear(root.wizardBody);
      var body = root.wizardBody;
      var review = ui.session.skillReview;
      body.appendChild(h(doc, "h4", { text: "A. 출처" }, []));
      body.appendChild(dl(doc, [
        ["선택한 파일", review.source.name],
        ["종류", review.source.kind],
        ["경고", review.source.warnings.join("; ") || "없음"],
        ["확인 필요", review.source.unknowns.join("; ") || "없음"]
      ]));
      body.appendChild(h(doc, "h4", { text: "B. 항상 다시 사용하는 값" }, []));
      body.appendChild(dl(doc, review.alwaysReusedOrDefault.map(function (row) {
        return [row.label, String(row.value)];
      })));
      body.appendChild(h(doc, "h4", { text: "C. 견적서마다 바뀌는 값" }, []));
      body.appendChild(dl(doc, review.changesEachQuote.map(function (row) {
        return [row.label, row.required ? "필수 입력" : "선택 입력"];
      })));
      body.appendChild(h(doc, "h4", { text: "D. 자동 계산 (견적 작성 시 자동 계산)" }, []));
      body.appendChild(dl(doc, review.calculatedByCore.map(function (row) {
        return [row.key, row.authority];
      })));
      var nameLabel = h(doc, "label", { htmlFor: "wiz-final-skill-name" }, ["내 견적서 이름 "]);
      nameLabel.appendChild(textInput(doc, "wiz-final-skill-name", ui.session.skillCandidate.name, {}));
      body.appendChild(h(doc, "div", { class: "fields" }, [nameLabel]));
      var flags = h(doc, "div", { class: "fields" }, []);
      var memoFlag = h(doc, "label", {}, []);
      var memoBox = h(doc, "input", { id: "wiz-flag-memo", type: "checkbox" }, []);
      memoBox.checked = ui.session.skillCandidate.variableSchema.memo === true;
      memoFlag.appendChild(memoBox);
      memoFlag.appendChild(doc.createTextNode(" 건별 비고 입력 허용"));
      flags.appendChild(memoFlag);
      var taxFlag = h(doc, "label", {}, []);
      var taxBox = h(doc, "input", { id: "wiz-flag-taxmode", type: "checkbox" }, []);
      taxBox.checked = ui.session.skillCandidate.variableSchema.taxMode === true;
      taxFlag.appendChild(taxBox);
      taxFlag.appendChild(doc.createTextNode(" 건별 세금 방식 변경 허용"));
      flags.appendChild(taxFlag);
      body.appendChild(flags);
      var actions = h(doc, "div", { class: "button-row" }, []);
      actions.appendChild(actionButton(doc, "wiz-skill-save", "내 견적서로 저장", "primary"));
      body.appendChild(actions);
    }

    function renderStep6() {
      setStep(6);
      clear(root.wizardBody);
      var body = root.wizardBody;
      body.appendChild(h(doc, "p", { text: "내 견적서로 저장되었습니다." }, []));
      body.appendChild(actionButton(doc, "wiz-write", "이 견적서로 작성", "primary"));
    }

    function failStatus(code) {
      var messages = {
        invalid_source_info: "파일 정보를 확인해 주세요.",
        sender_company_requires_correction: "회사명을 입력해 주세요.",
        valid_days_requires_correction: "기본 유효기간을 입력해 주세요.",
        tax_mode_requires_correction: "기본 세금 방식을 선택해 주세요.",
        template_not_approved: "승인된 모양이 아닙니다. 모양을 먼저 승인해 주세요.",
        skill_not_approved: "승인되지 않은 내 견적서는 저장할 수 없습니다.",
        commit_write_failed: "저장에 실패했습니다. 저장된 것은 없습니다."
      };
      announce(messages[code] || "처리하지 못했습니다. 다시 시도해 주세요.");
    }

    function onWizardClick(event) {
      var target = event && event.target && typeof event.target.closest === "function"
        ? event.target.closest("[data-action]")
        : null;
      if (!target) return;
      var action = target.getAttribute("data-action");
      handleAction(action, target);
    }

    function currentDraft() {
      return env.getDraftSnapshot ? env.getDraftSnapshot() : null;
    }

    function handleAction(action, target) {
      var id = action.indexOf(":") === -1 ? null : action.slice(action.indexOf(":") + 1);
      var base = action.indexOf(":") === -1 ? action : action.slice(0, action.indexOf(":"));
      if (base === "wiz-pick-file") {
        if (root.file) root.file.click();
        return;
      }
      if (base === "wiz-step2") {
        if (ui.analysisStatus === "loading") {
          ui.analysisToken += 1;
          ui.analysisStatus = "manual";
          ui.analysisError = null;
          ui.extraction = null;
          ui.facts = null;
        }
        renderStep2();
        return;
      }
      if (base === "wiz-facts-next") {
        ui.facts = readFactsForm();
        startTemplatePhase();
        return;
      }
      if (base === "wiz-preview-update") {
        var patch = readLayoutForm();
        var corrected = Session.correctTemplate(ui.session, { name: patch.name, content: patch.content }, { now: isoNow() });
        if (!corrected.ok) { failStatus(corrected.code); return; }
        ui.session = corrected.session;
        var preview = Session.previewTemplate(ui.session, currentDraft(), {});
        if (!preview.ok) { failStatus(preview.code); return; }
        env.renderPreviewModel(preview.renderModel);
        announce("미리보기를 업데이트했습니다. 저장된 것은 없습니다.");
        renderStep3();
        return;
      }
      if (base === "wiz-use-layout") {
        var patch2 = readLayoutForm();
        var corrected2 = Session.correctTemplate(ui.session, { name: patch2.name, content: patch2.content }, { now: isoNow() });
        if (!corrected2.ok) { failStatus(corrected2.code); return; }
        ui.session = corrected2.session;
        var approved = Session.approveTemplate(ui.session, {
          approvedBy: "local-owner", approvedAt: isoNow(), approvalRef: "b66-ui"
        }, { now: isoNow() });
        if (!approved.ok) { failStatus(approved.code); return; }
        ui.session = approved.session;
        buildSkillPhase();
        return;
      }
      if (base === "wiz-skill-save") {
        saveSkillPhase();
        return;
      }
      if (base === "wiz-write") {
        closeWizard();
        useActiveSkill(true);
        return;
      }
      if (base === "wiz-cancel-step") {
        closeWizard("등록을 취소했습니다. 저장된 것은 없습니다.");
        return;
      }
      if (base === "skill-use") {
        useSkillById(id);
        return;
      }
      if (base === "skill-rename") {
        ui.renamingSkillId = id;
        refreshSkills();
        var input = doc.getElementById("skill-rename-" + id);
        if (input && typeof input.focus === "function") input.focus();
        return;
      }
      if (base === "skill-rename-save") {
        var renameInput = doc.getElementById("skill-rename-" + id);
        var renamed = SkillStore.renameSkill
          ? SkillStore.renameSkill(readStore(), id, renameInput ? renameInput.value : "", { now: isoNow() })
          : null;
        if (!renamed || !renamed.ok) { failStatus(renamed ? renamed.code : "rename_failed"); return; }
        if (!SkillStore.writeStore(env.storage, renamed.store)) { failStatus("rename_failed"); return; }
        ui.renamingSkillId = null;
        refreshSkills();
        env.toast("내 견적서 이름을 변경했습니다.");
        return;
      }
      if (base === "skill-rename-cancel") {
        ui.renamingSkillId = null;
        refreshSkills();
        return;
      }
      if (base === "skill-delete") {
        var current = SkillStore.getSkill(readStore(), id);
        if (!current) { failStatus("skill_not_found"); return; }
        if (!env.confirm('"' + current.name + '" 내 견적서를 삭제할까요? 이 브라우저에서만 삭제됩니다.')) return;
        var deleted = SkillStore.deleteSkill(readStore(), id);
        if (!deleted.ok) { failStatus(deleted.code); return; }
        if (!SkillStore.writeStore(env.storage, deleted.store)) { failStatus("delete_failed"); return; }
        if (ui.activeSkillId === id) {
          ui.activeSkillId = null;
          env.applySkillToForm(null);
        }
        refreshSkills();
        env.renderMain();
        env.toast("내 견적서를 삭제했습니다.");
        return;
      }
      if (base === "skill-default") {
        var set = SkillStore.setDefaultSkill(readStore(), id);
        if (!set.ok) { failStatus(set.code); return; }
        if (!SkillStore.writeStore(env.storage, set.store)) { failStatus("default_failed"); return; }
        refreshSkills();
        env.toast("기본 내 견적서로 설정했습니다.");
        return;
      }
      if (base === "skill-default-clear") {
        var cleared = SkillStore.setDefaultSkill(readStore(), "");
        if (!cleared.ok) { failStatus(cleared.code); return; }
        if (!SkillStore.writeStore(env.storage, cleared.store)) { failStatus("default_failed"); return; }
        refreshSkills();
        env.toast("기본 설정을 해제했습니다.");
        return;
      }
    }

    function isoNow() {
      try {
        return new Date().toISOString();
      } catch (err) {
        return "";
      }
    }

    function startTemplatePhase() {
      var started = Session.start({
        filename: ui.fileMeta.name,
        mediaType: ui.fileMeta.mediaType,
        byteSize: ui.fileMeta.byteSize
      }, { now: isoNow(), sourceMode: "fact_reference" });
      if (!started.ok) { failStatus(started.code); return; }
      ui.session = started.session;
      announce(started.draftNote);
      renderStep3();
    }

    function buildSkillPhase() {
      var kind = extractionKindForCategory(ui.fileMeta.category);
      var corrections = {
        sender: {
          company: ui.facts.sender.company,
          rep: ui.facts.sender.rep,
          bizNo: ui.facts.sender.bizNo,
          address: ui.facts.sender.address,
          phone: ui.facts.sender.phone,
          email: ui.facts.sender.email
        },
        validDays: ui.facts.validDays,
        taxMode: ui.facts.taxMode,
        memo: ui.facts.memo,
        skillName: ui.facts.skillName
      };
      var built = Session.buildSkillCandidate(ui.session, {
        modelOutput: registrationModelOutput(ui.extraction, kind, ui.fileMeta.name),
        sourceMeta: {
          sourceKind: "file",
          filename: ui.fileMeta.name,
          sourceRef: ui.extraction ? ("server:" + extractionKindForCategory(ui.fileMeta.category) + "-analysis") : "media:" + ui.fileMeta.mediaType,
          capturedAt: isoNow()
        },
        corrections: corrections
      }, { now: isoNow() });
      if (!built.ok) { failStatus(built.code); return; }
      ui.session = built.session;
      renderStep5();
    }

    function saveSkillPhase() {
      var nameNode = doc.getElementById("wiz-final-skill-name");
      var memoNode = doc.getElementById("wiz-flag-memo");
      var taxNode = doc.getElementById("wiz-flag-taxmode");
      var patch = {};
      if (nameNode && String(nameNode.value).trim() && String(nameNode.value).trim() !== ui.session.skillCandidate.name) {
        patch.name = String(nameNode.value).trim();
      }
      var flags = {};
      if (memoNode) flags.memo = Boolean(memoNode.checked);
      if (taxNode) flags.taxMode = Boolean(taxNode.checked);
      patch.variableSchema = Object.assign({}, ui.session.skillCandidate.variableSchema, flags);
      if (patch.name !== undefined || memoNode || taxNode) {
        var edited = Session.correctSkill(ui.session, patch, { now: isoNow() });
        if (!edited.ok) { failStatus(edited.code); return; }
        ui.session = edited.session;
      }
      var approved = Session.approveSkill(ui.session, {
        approvedBy: "local-owner", now: isoNow(), approvalRef: "b66-ui"
      });
      if (!approved.ok) { failStatus(approved.code); return; }
      ui.session = approved.session;
      var committed = Session.commit(ui.session, {
        templateStore: TemplateStore.readStore(env.storage),
        skillStore: readStore()
      }, env.storage, { now: isoNow() });
      if (!committed.ok) {
        failStatus(committed.code);
        return;
      }
      ui.session = committed.session;
      ui.activeSkillId = committed.skill.id;
      refreshSkills();
      env.renderMain();
      renderStep6();
      announce("내 견적서로 저장되었습니다.");
    }

    function useSkillById(id) {
      var skill = SkillStore.getSkill(readStore(), id);
      if (!skill) { failStatus("skill_not_found"); return; }
      ui.activeSkillId = id;
      env.applySkillToForm(skill);
      refreshSkills();
      env.renderMain();
    }

    function useActiveSkill(focusForm) {
      if (!ui.activeSkillId) {
        env.applySkillToForm(null);
        env.toast("기본 견적서로 작성합니다.");
        return;
      }
      var skill = SkillStore.getSkill(readStore(), ui.activeSkillId);
      if (!skill) {
        ui.activeSkillId = null;
        refreshSkills();
        env.applySkillToForm(null);
        return;
      }
      env.applySkillToForm(skill);
      env.renderMain();
      if (focusForm && typeof env.focusMain === "function") env.focusMain();
    }

    function onSelectChange() {
      var value = root.select ? String(root.select.value || "") : "";
      if (!value) {
        ui.activeSkillId = null;
        env.applySkillToForm(null);
        refreshSkills();
        env.renderMain();
        return;
      }
      useSkillById(value);
    }

    function onManageToggle() {
      if (!root.managePanel || !root.manageToggle) return;
      var open = root.managePanel.hidden;
      root.managePanel.hidden = !open;
      root.manageToggle.setAttribute("aria-expanded", String(open));
    }

    function onFileChange() {
      var input = root.file;
      var file = input && input.files && input.files[0];
      if (root.file) root.file.value = "";
      if (!file) return;
      var classified = FileIntake.classifyFile({ name: file.name, type: file.type, size: file.size });
      if (!classified.ok) {
        announce(FileIntake.errorMessage(classified));
        return;
      }

      ui.analysisToken += 1;
      var token = ui.analysisToken;
      ui.fileMeta = classified.value;
      ui.extraction = null;
      ui.facts = null;
      ui.analysisError = null;

      ui.analysisStatus = "loading";
      renderStep1();
      announce((classified.value.category === "image" ? "선택한 이미지" : "선택한 문서") + "에서 견적 내용을 분석하고 있습니다.");

      var fetchFn = env.fetch || (typeof fetch === "function" ? fetch.bind(globalThis) : null);
      analyzeFile(file, classified.value, fetchFn).then(function (result) {
        if (token !== ui.analysisToken) return;
        if (result.ok) {
          ui.extraction = result.extraction;
          ui.facts = factsFromExtraction(result.extraction);
          ui.analysisStatus = "ready";
          ui.analysisError = null;
          renderStep1();
          announce((classified.value.category === "image" ? "이미지" : "문서") + " 내용 분석이 끝났습니다. 추출값을 확인해 주세요.");
          return;
        }
        ui.extraction = null;
        ui.facts = null;
        ui.analysisStatus = "error";
        ui.analysisError = result.code || "analysis_failed";
        renderStep1();
        announce("자동 분석을 완료하지 못했습니다. 원본과 비교해 직접 확인하며 등록할 수 있습니다.");
      });
    }

    if (root.wizardBody) {
      root.wizardBody.addEventListener("click", onWizardClick);
    }
    if (root.list) {
      root.list.addEventListener("click", onWizardClick);
    }
    if (root.select) {
      root.select.addEventListener("change", onSelectChange);
    }
    if (root.register) {
      root.register.addEventListener("click", function () { openWizard(root.register); });
    }
    if (root.write) {
      root.write.addEventListener("click", function () { useActiveSkill(true); });
    }
    if (root.manageToggle) {
      root.manageToggle.addEventListener("click", onManageToggle);
    }
    if (root.wizardCancel) {
      root.wizardCancel.addEventListener("click", function () {
        Session.cancel(ui.session);
        closeWizard("등록을 취소했습니다. 저장된 것은 없습니다.");
      });
    }
    if (root.file) {
      root.file.addEventListener("change", onFileChange);
    }

    refreshSkills();

    return {
      ids: IDS,
      refresh: refreshSkills,
      getState: function () { return ui; },
      useActiveSkill: useActiveSkill,
      actions: {
        openWizard: openWizard,
        closeWizard: closeWizard,
        handleAction: handleAction,
        onFileChange: onFileChange,
        onSelectChange: onSelectChange
      }
    };
  }

  return {
    IDS: IDS,
    BUILTIN_OPTION_VALUE: BUILTIN_OPTION_VALUE,
    BUILTIN_OPTION_LABEL: BUILTIN_OPTION_LABEL,
    STEP_TITLES: STEP_TITLES,
    buildSkillOptions: buildSkillOptions,
    buildSkillRows: buildSkillRows,
    formValuesFromSkill: formValuesFromSkill,
    wizardStepForSession: wizardStepForSession,
    extractionKindForCategory: extractionKindForCategory,
    analyzeFile: analyzeFile,
    analyzeImageFile: analyzeImageFile,
    factsFromExtraction: factsFromExtraction,
    registrationModelOutput: registrationModelOutput,
    LIVE_INTAKE_ENDPOINT: LIVE_INTAKE_ENDPOINT,
    bindSkillSection: bindSkillSection
  };
});
