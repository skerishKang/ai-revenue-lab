/* B66 · CompanyProfile self-service settings (#3406) — company-profile-settings.js

   "설정 → 내 회사" secondary surface + first-login bounded onboarding.

   원칙:
   - canonical authority 는 인증된 서버 세션의 CompanyProfile 이다
     (GET/PUT /api/padiem/b66/company-profile). 브라우저 저장소는 authority 가 아니며
     이 모듈은 계정 범위(owner/workspace) 값을 절대 전송하지 않는다.
   - CompanyProfile 은 회사 식별/연락 사실(account identity/contact facts)만 다룬다.
     유효기간/부가세 등 quote-family 정책은 승인된 Saved Quote Skill 이 우선하며
     이 화면의 기본값은 "양식에 family 값이 없을 때만 쓰이는 account fallback"이다.
   - assisted/alpha 고객(CGI)은 이미 pre-provisioned 되어 있다: profile 이 ready 하면
     onboarding 안내를 절대 보여주지 않는다.
   - DOM API(createElement/textContent)로만 렌더한다. innerHTML 을 쓰지 않는다.
   - 저장 성공 후 페이지를 새로고침해 padiem-account 의 canonical 상태가 재로드되게 한다
     (로컬 캐시를 authority 처럼 다루지 않기 위함).

   (브라우저/Node 양쪽에서 실행. Node 에서는 doc/fetch/session 스텁을 주입한다) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(root);
  } else {
    root.CompanyProfileSettings = factory(root);
  }
})(typeof self !== "undefined" ? self : this, function (root) {
  "use strict";

  var API_BASE = "/api/padiem";
  var PROFILE_ENDPOINT = "/b66/company-profile";
  var ONBOARDING_DISMISS_KEY = "companyProfileSetupPrompt.v1";

  var TAX_MODE_OPTIONS = [
    { value: "", label: "미설정" },
    { value: "EXCLUSIVE", label: "별도 (공급가액 + 부가세)" },
    { value: "INCLUSIVE", label: "포함 (공급가액에 부가세 포함)" },
    { value: "EXEMPT", label: "면세" }
  ];

  var FIELD_DEFS = [
    { key: "company", label: "회사명", type: "text", maxlength: 500, required: true },
    { key: "representative", label: "대표자", type: "text", maxlength: 500, required: false },
    { key: "contactPerson", label: "담당자", type: "text", maxlength: 500, required: false },
    { key: "businessNumber", label: "사업자번호", type: "text", maxlength: 80, required: false },
    { key: "address", label: "주소", type: "text", maxlength: 500, required: false },
    { key: "phone", label: "전화", type: "text", maxlength: 100, required: false },
    { key: "email", label: "이메일", type: "email", maxlength: 320, required: false },
    { key: "defaultValidityDays", label: "기본 유효기간(일)", type: "number", maxlength: 4, required: false },
    { key: "defaultTaxMode", label: "기본 부가세 방식", type: "select", maxlength: 0, required: false }
  ];

  function defaultDeps() {
    return {
      doc: root.document || null,
      fetchJson: null, /* lazily bound to root.fetch */
      host: null,
      settingsPanel: null,
      reload: function () { root.location.reload(); },
      session: (function () {
        try { return root.sessionStorage || null; } catch (_) { return null; }
      })(),
      now: function () { return Date.now(); }
    };
  }

  function profileValuesFromRaw(raw) {
    var values = {};
    FIELD_DEFS.forEach(function (field) {
      var value = raw && typeof raw === "object" ? raw[field.key] : null;
      values[field.key] = value === undefined || value === null ? "" : String(value);
    });
    return values;
  }

  function validateProfileValues(values) {
    var errors = {};
    var payload = {};
    FIELD_DEFS.forEach(function (field) {
      var raw = values[field.key];
      var text = raw === undefined || raw === null ? "" : String(raw).trim();
      if (!text) {
        if (field.required) errors[field.key] = field.label + "을(를) 입력해 주세요.";
        return;
      }
      if (field.type === "number") {
        var parsed = Number(text);
        if (!isFinite(parsed) || Math.floor(parsed) !== parsed || parsed < 0 || parsed > 3650) {
          errors[field.key] = "0 ~ 3650 사이의 정수를 입력해 주세요.";
          return;
        }
        payload[field.key] = parsed;
        return;
      }
      if (field.key === "defaultTaxMode") {
        var known = TAX_MODE_OPTIONS.some(function (option) { return option.value === text; });
        if (!known || !text) {
          errors[field.key] = "부가세 방식을 선택해 주세요.";
          return;
        }
        payload[field.key] = text;
        return;
      }
      if (text.length > field.maxlength) {
        errors[field.key] = field.label + "이(가) 너무 깁니다.";
        return;
      }
      if (field.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)) {
        errors[field.key] = "이메일 형식을 확인해 주세요.";
        return;
      }
      payload[field.key] = text;
    });
    var hasAny = Object.keys(payload).some(function (key) {
      return payload[key] !== "" && payload[key] !== null && payload[key] !== undefined;
    });
    if (!hasAny && !Object.keys(errors).length) {
      errors.company = "회사명을 입력해 주세요.";
    }
    return { ok: Object.keys(errors).length === 0, errors: errors, payload: payload };
  }

  function el(doc, tag, className, text) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function buildProfileForm(doc, values, state) {
    /* state: "onboarding" | "edit" — DOM API 만 사용 */
    var form = el(doc, "form", "company-profile-form");
    form.setAttribute("novalidate", "novalidate");
    FIELD_DEFS.forEach(function (field) {
      var row = el(doc, "div", "company-profile-field");
      var label = el(doc, "label", null, field.required ? field.label + " *" : field.label);
      label.setAttribute("for", "cpField-" + field.key);
      row.appendChild(label);
      var input;
      if (field.type === "select") {
        input = el(doc, "select");
        TAX_MODE_OPTIONS.forEach(function (option) {
          var opt = el(doc, "option", null, option.label);
          opt.setAttribute("value", option.value);
          input.appendChild(opt);
        });
      } else {
        input = el(doc, "input");
        input.setAttribute("type", field.type);
        if (field.maxlength) input.setAttribute("maxlength", String(field.maxlength));
      }
      input.id = "cpField-" + field.key;
      input.name = field.key;
      input.value = values[field.key] !== undefined ? String(values[field.key]) : "";
      if (field.key === "defaultValidityDays") {
        input.setAttribute("min", "0");
        input.setAttribute("max", "3650");
        input.setAttribute("step", "1");
        input.setAttribute("placeholder", "미설정");
      }
      row.appendChild(input);
      var error = el(doc, "div", "company-profile-field-error");
      error.setAttribute("data-error-for", field.key);
      row.appendChild(error);
      form.appendChild(row);
    });
    var actions = el(doc, "div", "company-profile-actions");
    var save = el(doc, "button", "company-profile-save", state === "onboarding" ? "저장하고 시작하기" : "저장");
    save.setAttribute("type", "button");
    save.setAttribute("id", "cpSave");
    actions.appendChild(save);
    if (state === "onboarding") {
      var skip = el(doc, "button", "company-profile-skip", "나중에 설정하기");
      skip.setAttribute("type", "button");
      skip.setAttribute("id", "cpSkip");
      actions.appendChild(skip);
    }
    form.appendChild(actions);
    var status = el(doc, "div", "company-profile-status");
    status.setAttribute("id", "cpStatus");
    form.appendChild(status);
    return form;
  }

  function bindCompanyProfileSection(deps) {
    var d = deps || defaultDeps();
    var doc = d.doc;
    var host = d.host;
    var state = { authenticated: null, profile: null, phase: "loading" };

    function apiFetch(path, options) {
      if (typeof d.fetchJson === "function") return d.fetchJson(path, options);
      var opts = Object.assign({
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Accept": "application/json" }
      }, options || {});
      var response = root.fetch(API_BASE + path, opts);
      return Promise.resolve(response).then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          return { response: res, data: data };
        });
      });
    }

    function setStatus(text, kind) {
      var status = host.querySelector("#cpStatus");
      if (!status) return;
      status.textContent = text || "";
      status.setAttribute("data-kind", kind || "info");
    }

    function clearFieldErrors(formNode) {
      if (!formNode) return;
      formNode.querySelectorAll("[data-error-for]").forEach(function (node) {
        node.textContent = "";
      });
    }

    function showFieldErrors(formNode, errors) {
      Object.keys(errors || {}).forEach(function (key) {
        var node = formNode.querySelector('[data-error-for="' + key + '"]');
        if (node) node.textContent = errors[key];
      });
    }

    function formValues() {
      var values = {};
      FIELD_DEFS.forEach(function (field) {
        var node = host.querySelector("#cpField-" + field.key);
        values[field.key] = node ? node.value : "";
      });
      return values;
    }

    function renderSignedOut() {
      state.phase = "signed-out";
      host.textContent = "";
      host.appendChild(el(doc, "p", "company-profile-note", "로그인하면 내 회사 정보를 설정하고 기기와 관계없이 재사용할 수 있습니다."));
    }

    function renderError(message) {
      state.phase = "error";
      host.textContent = "";
      var node = el(doc, "p", "company-profile-error", message);
      var retry = el(doc, "button", "company-profile-retry", "다시 시도");
      retry.setAttribute("type", "button");
      retry.setAttribute("id", "cpRetry");
      retry.addEventListener("click", function () { refresh(); });
      host.appendChild(node);
      host.appendChild(retry);
    }

    function renderForm(phase) {
      state.phase = phase;
      var values = profileValuesFromRaw(state.profile);
      host.textContent = "";
      if (phase === "onboarding") {
        host.appendChild(el(doc, "p", "company-profile-offer", "내 회사 정보를 먼저 설정할까요?"));
        host.appendChild(el(doc, "p", "company-profile-note",
          "견적서에 사용될 회사 기본정보를 저장해 두면 다음 견적부터 재사용합니다. 회사명만 입력해도 저장할 수 있습니다."));
      } else {
        host.appendChild(el(doc, "p", "company-profile-note",
          "견적서 발신자 기본정보입니다. 승인된 견적 양식(Saved Quote Skill)에 유효기간/부가세 등 family 기본값이 있으면 양식 값이 우선하며, 이 화면의 기본값은 양식에 값이 없을 때만 사용됩니다."));
      }
      var form = buildProfileForm(doc, values, phase);
      host.appendChild(form);
      var save = form.querySelector("#cpSave");
      save.addEventListener("click", function () { submit(); });
      var skip = form.querySelector("#cpSkip");
      if (skip) {
        skip.addEventListener("click", function () {
          if (d.session) {
            try { d.session.setItem(ONBOARDING_DISMISS_KEY, "dismissed"); } catch (_) {}
          }
          host.textContent = "";
          host.appendChild(el(doc, "p", "company-profile-note",
            "나중에 설정해도 됩니다. 견적에 회사 정보가 필요하면 이 화면(설정 → 내 회사)에서 설정할 수 있습니다."));
        });
      }
    }

    function maybeAutoOpenPanel() {
      if (!d.settingsPanel || !d.session) return;
      var dismissed = null;
      try { dismissed = d.session.getItem(ONBOARDING_DISMISS_KEY); } catch (_) { dismissed = null; }
      if (dismissed) return;
      d.settingsPanel.hidden = false;
    }

    function refresh(authenticatedHint) {
      state.phase = "loading";
      host.textContent = "";
      host.appendChild(el(doc, "p", "company-profile-note", "내 회사 정보를 확인하고 있습니다."));
      return apiFetch(PROFILE_ENDPOINT).then(function (result) {
        var ok = result.response && result.response.ok;
        var data = result.data;
        if (result.response && result.response.status === 401) {
          renderSignedOut();
          state.authenticated = false;
          return;
        }
        if (!ok || !data || data.ok !== true) {
          renderError("회사 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
          return;
        }
        state.authenticated = true;
        if (data.state === "missing" || !data.company_profile) {
          state.profile = null;
          renderForm("onboarding");
          if (authenticatedHint !== false) maybeAutoOpenPanel();
          return;
        }
        state.profile = data.company_profile;
        renderForm("edit");
      }, function () {
        renderError("회사 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      });
    }

    function submit() {
      if (state.phase !== "onboarding" && state.phase !== "edit") return Promise.resolve();
      var form = host.querySelector("form.company-profile-form");
      var values = formValues();
      var validation = validateProfileValues(values);
      clearFieldErrors(form);
      if (!validation.ok) {
        showFieldErrors(form, validation.errors);
        return Promise.resolve();
      }
      var save = host.querySelector("#cpSave");
      if (save) { save.disabled = true; }
      setStatus("저장하고 있습니다.", "info");
      return apiFetch(PROFILE_ENDPOINT, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(validation.payload)
      }).then(function (result) {
        if (result.response && result.response.status === 401) {
          renderSignedOut();
          return;
        }
        if (!result.response || !result.response.ok || !result.data || result.data.ok !== true) {
          if (save) { save.disabled = false; }
          var code = result.data && result.data.error ? result.data.error.code : null;
          if (code === "invalid_company_profile") {
            setStatus("회사정보 값을 확인해 주세요.", "error");
          } else if (code === "forbidden_owner_field" || code === "unsupported_field") {
            setStatus("요청 형식이 올바르지 않습니다. 새로고침 후 다시 시도해 주세요.", "error");
          } else {
            setStatus("저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
          }
          return;
        }
        state.profile = result.data.company_profile;
        if (d.session) {
          try { d.session.setItem(ONBOARDING_DISMISS_KEY, "configured"); } catch (_) {}
        }
        setStatus("저장했습니다. 화면을 새로고침합니다.", "ok");
        setTimeout(function () { d.reload(); }, d.reloadDelay === undefined ? 400 : d.reloadDelay);
      }, function () {
        if (save) { save.disabled = false; }
        setStatus("저장하지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
      });
    }

    if (doc && typeof doc.addEventListener === "function") {
      doc.addEventListener("b66:auth-changed", function (event) {
        var authenticated = event && event.detail ? event.detail.authenticated : null;
        if (authenticated === false) {
          state.profile = null;
          renderSignedOut();
          return;
        }
        refresh(authenticated);
      });
    }

    return {
      host: host,
      refresh: refresh,
      submit: submit,
      formValues: formValues,
      state: function () { return state; }
    };
  }

  function autoBind() {
    var doc = root.document;
    if (!doc) return null;
    var host = doc.getElementById("companyProfileHost");
    var panel = doc.getElementById("settingsPanel");
    if (!host) return null;
    return bindCompanyProfileSection({
      doc: doc,
      host: host,
      settingsPanel: panel,
      reload: function () { root.location.reload(); }
    });
  }

  (function init() {
    if (typeof root.document === "undefined") return;
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", autoBind);
    } else {
      autoBind();
    }
  })();

  return {
    API_BASE: API_BASE,
    PROFILE_ENDPOINT: PROFILE_ENDPOINT,
    FIELD_DEFS: FIELD_DEFS,
    TAX_MODE_OPTIONS: TAX_MODE_OPTIONS,
    ONBOARDING_DISMISS_KEY: ONBOARDING_DISMISS_KEY,
    profileValuesFromRaw: profileValuesFromRaw,
    validateProfileValues: validateProfileValues,
    buildProfileForm: buildProfileForm,
    bindCompanyProfileSection: bindCompanyProfileSection,
    autoBind: autoBind
  };
});
