/*
 * #7460 / #7173 PR2 · Util tools inside the Util app (#util/speech, #util/sns,
 * #util/meeting).
 *
 * File boundary: the screens live here (and in util-tools.css); field schemas
 * come from window.PadiemUtilManifest (static/util-manifest.js); prompt shapes
 * and /api/chat/stream calls live in util-tools-contract.js. app.js gains
 * nothing (R5 #7216).
 *
 * Layout (#7460): PC (>= 921px) places Left Input (.util-pane-input) and Right
 * Result (.util-pane-result) side by side; Phone (<= 920px) stacks them.
 * "더 자세히" (<details class="util-more">) stays collapsed by default.
 */
(() => {
  "use strict";

  const TOOL_KEYS = Object.freeze(["speech", "sns", "meeting"]);

  const T = Object.freeze({
    ko: Object.freeze({
      loginRequired: "로그인 후 이용할 수 있습니다.",
      loginUnknown: "로그인 상태를 확인하는 중입니다.",
      login: "로그인",
      required: "필수 항목을 입력해 주세요.",
      generating: "생성 중…",
      result: "생성 결과",
      emptyResult: "왼쪽 입력 칸을 채우고 생성을 누르면 여기에 초안이 표시됩니다.",
      copy: "복사",
      copied: "복사됨",
      copyFailed: "복사하지 못했습니다.",
      regenerate: "다시 만들기",
      more: "더 자세히 (날짜·장소·메시지·말투)",
      speechGenerate: "초안 생성",
      snsGenerate: "게시글 생성",
      meetingGenerate: "요약 생성",
      meetingResult: "회의 요약",
      platformGroup: "게시할 곳",
    }),
    en: Object.freeze({
      loginRequired: "Sign in to use this tool.",
      loginUnknown: "Checking your sign-in state.",
      login: "Sign in",
      required: "Fill in the required fields.",
      generating: "Generating…",
      result: "Result",
      emptyResult: "Fill in the fields and generate to see the draft here.",
      copy: "Copy",
      copied: "Copied",
      copyFailed: "Couldn’t copy.",
      regenerate: "Generate again",
      more: "More (date, place, message, tone)",
      speechGenerate: "Draft the address",
      snsGenerate: "Draft the post",
      meetingGenerate: "Summarize the meeting",
      meetingResult: "Meeting summary",
      platformGroup: "Where it goes",
    }),
  });

  // Fallback field schemas when a unit test executes util-tools.js without
  // preloading util-manifest.js; in the page, PadiemUtilManifest wins.
  const FALLBACK_SCHEMAS = Object.freeze({
    speech: Object.freeze([
      { key: "event", type: "text", required: true, advanced: false, label: { ko: "행사명", en: "Event name" }, placeholder: { ko: "예: 제78주년 광복절 기념식", en: "" } },
      { key: "audience", type: "text", required: false, advanced: false, label: { ko: "참석 대상", en: "Audience" }, placeholder: { ko: "예: 지역 주민 200명", en: "" } },
      { key: "author", type: "text", required: false, advanced: false, label: { ko: "직책과 이름", en: "Title & speaker name" }, placeholder: { ko: "예: 지역구 국회의원 김의민", en: "" } },
      { key: "length", type: "select", required: false, advanced: false, defaultValue: "medium", label: { ko: "분량", en: "Length" }, options: [{ value: "short", label: { ko: "1분", en: "1 min" } }, { value: "medium", label: { ko: "3분", en: "3 min" } }, { value: "long", label: { ko: "5분", en: "5 min" } }] },
      { key: "date", type: "date", required: false, advanced: true, label: { ko: "행사 날짜", en: "Event date" }, placeholder: { ko: "", en: "" } },
      { key: "place", type: "text", required: false, advanced: true, label: { ko: "장소", en: "Venue" }, placeholder: { ko: "예: 시청 대강당", en: "" } },
      { key: "nature", type: "text", required: false, advanced: true, label: { ko: "행사 성격", en: "Event type" }, placeholder: { ko: "예: 지역 행사", en: "" } },
      { key: "message", type: "textarea", rows: 3, required: false, advanced: true, label: { ko: "주요 메시지", en: "Key message" }, placeholder: { ko: "예: 함께 성장하는 지역사회", en: "" } },
      { key: "emphasis", type: "textarea", rows: 3, required: false, advanced: true, label: { ko: "강조 내용", en: "Points to emphasize" }, placeholder: { ko: "예: 상생과 배려", en: "" } },
      { key: "tone", type: "select", required: false, advanced: true, defaultValue: "formal", label: { ko: "말투", en: "Tone" }, options: [{ value: "formal", label: { ko: "공식", en: "Formal" } }, { value: "warm", label: { ko: "따뜻한", en: "Warm" } }, { value: "concise", label: { ko: "간결", en: "Concise" } }] },
      { key: "style", type: "textarea", rows: 4, required: false, advanced: true, label: { ko: "기존 축사 샘플 (말투 반영)", en: "Sample address" }, placeholder: { ko: "기존 축사/인사말 원문 붙여넣기", en: "" } },
    ]),
    sns: Object.freeze([
      { key: "event", type: "text", required: true, advanced: false, label: { ko: "행사명", en: "Topic / event" }, placeholder: { ko: "예: 주민 정원 사업 설명회", en: "" } },
      { key: "whenwhere", type: "text", required: false, advanced: false, label: { ko: "날짜·장소", en: "Date & place" }, placeholder: { ko: "예: 10월 30일 오후 2시, 구청 소회의실", en: "" } },
      { key: "content", type: "textarea", rows: 4, required: true, advanced: false, label: { ko: "주요 내용", en: "Key details" }, placeholder: { ko: "예: 정원 사업 신청 방법과 지원 금액 안내", en: "" } },
      { key: "audience", type: "text", required: false, advanced: false, label: { ko: "대상 독자", en: "Target readers" }, placeholder: { ko: "예: 구내 상인", en: "" } },
      { key: "memo", type: "textarea", rows: 4, required: false, advanced: false, label: { ko: "메모", en: "Extra notes" }, placeholder: { ko: "예: 참석자에게 강조할 한 가지", en: "" } },
      { key: "tone", type: "select", required: false, advanced: false, defaultValue: "professional", label: { ko: "문체", en: "Tone" }, options: [{ value: "casual", label: { ko: "캐주얼", en: "Casual" } }, { value: "professional", label: { ko: "전문적", en: "Professional" } }, { value: "emotional", label: { ko: "감성적", en: "Emotional" } }] },
      { key: "platform", type: "choice", required: false, advanced: false, defaultValue: "blog", label: { ko: "게시할 곳", en: "Where it goes" }, options: [{ value: "blog", label: { ko: "블로그", en: "Blog" } }, { value: "facebook", label: { ko: "페이스북", en: "Facebook" } }, { value: "instagram", label: { ko: "인스타그램", en: "Instagram" } }] },
    ]),
    meeting: Object.freeze([
      { key: "title", type: "text", required: true, advanced: false, label: { ko: "회의명", en: "Meeting title" }, placeholder: { ko: "예: 10월 주민 민원 회의", en: "" } },
      { key: "when", type: "datetime-local", required: false, advanced: false, label: { ko: "회의 일시", en: "Date & time" }, placeholder: { ko: "", en: "" } },
      { key: "attendees", type: "text", required: false, advanced: false, label: { ko: "참석자", en: "Attendees" }, placeholder: { ko: "예: 비서실장, 지역 담당", en: "" } },
      { key: "content", type: "textarea", rows: 8, required: true, advanced: false, label: { ko: "회의 내용", en: "Meeting notes / transcript" }, placeholder: { ko: "회의에서 오간 내용을 그대로 적어 주세요", en: "" } },
    ]),
  });

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key) {
    const table = T[lang()] || T.ko;
    return table[key] !== undefined ? table[key] : T.ko[key];
  }

  function localized(entry) {
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[lang()] || entry.ko || "";
  }

  function contract() {
    return window.PadiemUtilContract || null;
  }

  function schemaFor(toolId) {
    const reg = window.PadiemUtilManifest;
    const tool = reg && typeof reg.getTool === "function" ? reg.getTool(toolId) : null;
    if (tool && Array.isArray(tool.fields) && tool.fields.length) return tool.fields;
    return FALLBACK_SCHEMAS[toolId] || [];
  }

  function requiredKeysFor(toolId) {
    return schemaFor(toolId).filter((f) => f.required).map((f) => f.key);
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderAnswer(host, value) {
    host.removeAttribute("data-empty");
    const markdown = window.PadiemUtilMarkdown;
    if (markdown && typeof markdown.render === "function") {
      markdown.render(host, value);
      return;
    }
    host.textContent = value;
  }

  function paintEmptyResult(host) {
    host.setAttribute("data-empty", "true");
    host.replaceChildren(element("p", "util-result-empty", t("emptyResult")));
  }

  function plainAnswer(value) {
    const markdown = window.PadiemUtilMarkdown;
    return markdown && typeof markdown.plain === "function"
      ? markdown.plain(value)
      : String(value == null ? "" : value);
  }

  function authSession() {
    try {
      if (window.PadiemAuthSession && typeof window.PadiemAuthSession.get === "function") {
        const session = window.PadiemAuthSession.get();
        return session && typeof session === "object" ? session : null;
      }
    } catch (_) { /* an unreadable session is treated as unknown */ }
    return null;
  }

  function loginGate(known) {
    const gate = element("div", "util-gate");
    gate.appendChild(element("p", "util-gate-text", known ? t("loginRequired") : t("loginUnknown")));
    const login = element("button", "util-gate-login", t("login"));
    login.type = "button";
    login.setAttribute("data-util-login", "");
    login.addEventListener("click", () => {
      const button = document.getElementById("loginButton");
      if (button && typeof button.click === "function") button.click();
    });
    gate.appendChild(login);
    return gate;
  }

  function buildFieldNode(spec, state) {
    if (spec.type === "choice") {
      const tabs = element("div", "util-platform-tabs");
      tabs.setAttribute("role", "group");
      tabs.setAttribute("aria-label", localized(spec.label) || t("platformGroup"));
      const holder = element("div", "util-field util-field-tabs");
      const options = Array.isArray(spec.options) && spec.options.length
        ? spec.options
        : Object.keys(contract().PLATFORM_TITLE).map((key) => ({ value: key, label: contract().PLATFORM_TITLE[key] }));
      options.forEach((opt) => {
        const key = opt.value;
        const button = element("button", "util-platform-tab", localized(opt.label) || contract().PLATFORM_TITLE[key] || key);
        button.type = "button";
        button.setAttribute("data-platform", key);
        button.setAttribute("aria-pressed", key === state.platform ? "true" : "false");
        button.addEventListener("click", () => {
          state.platform = key;
          Array.prototype.forEach.call(tabs.querySelectorAll("[data-platform]"), (node) => {
            node.setAttribute("aria-pressed", node.getAttribute("data-platform") === key ? "true" : "false");
          });
          if (state.onPlatform) state.onPlatform(key);
        });
        tabs.appendChild(button);
      });
      holder.appendChild(tabs);
      return holder;
    }

    const label = element("label", "util-field");
    label.appendChild(element("span", "util-field-label", localized(spec.label)));
    let input;
    if (spec.type === "textarea") {
      input = element("textarea", "util-input");
      input.rows = spec.rows || 3;
    } else if (spec.type === "select") {
      input = element("select", "util-input");
      (spec.options || []).forEach((opt) => {
        const option = element("option", null, localized(opt.label));
        option.value = opt.value;
        option.selected = opt.value === spec.defaultValue;
        input.appendChild(option);
      });
    } else {
      input = element("input", "util-input");
      input.type = spec.type || "text";
    }
    input.name = spec.key;
    input.id = "utilToolField-" + spec.key;
    label.setAttribute("for", input.id);
    if (spec.required) {
      input.required = true;
      input.setAttribute("aria-invalid", "false");
      input.addEventListener("input", () => {
        if (String(input.value || "").trim()) input.setAttribute("aria-invalid", "false");
      });
    }
    const ph = localized(spec.placeholder);
    if (ph) input.placeholder = ph;
    label.appendChild(input);
    return label;
  }

  function buildFormFields(toolId, form, state) {
    const fields = schemaFor(toolId);
    const primaryFields = fields.filter((f) => !f.advanced);
    const advancedFields = fields.filter((f) => f.advanced);
    primaryFields.forEach((spec) => form.appendChild(buildFieldNode(spec, state)));
    if (advancedFields.length) {
      // #7460: "더 자세히" stays collapsed by default (native <details> without open).
      const more = element("details", "util-more");
      more.appendChild(element("summary", "util-more-summary", t("more")));
      const body = element("div", "util-more-body");
      advancedFields.forEach((spec) => body.appendChild(buildFieldNode(spec, state)));
      more.appendChild(body);
      form.appendChild(more);
    }
  }

  function readValues(form) {
    const values = {};
    Array.prototype.forEach.call(form.querySelectorAll("[name]"), (input) => {
      values[input.name] = typeof input.value === "string" ? input.value.trim() : "";
    });
    return values;
  }

  function generateLabel(toolId) {
    if (toolId === "speech") return t("speechGenerate");
    return toolId === "sns" ? t("snsGenerate") : t("meetingGenerate");
  }

  function buildScreen(toolId) {
    const state = { platform: "blog", onPlatform: null };
    const wrap = element("div", "util-tool-form util-tool-workbench");
    wrap.setAttribute("data-util-form", toolId);

    const inputPane = element("div", "util-pane-input");
    inputPane.setAttribute("data-util-pane", "input");

    const form = element("form", "util-form");
    form.id = "utilToolForm-" + toolId;
    form.noValidate = true;
    buildFormFields(toolId, form, state);

    const actions = element("div", "util-form-actions");
    const primary = element("button", "util-generate", generateLabel(toolId));
    primary.type = "submit";
    primary.id = "utilGenerate-" + toolId;
    actions.appendChild(primary);
    form.appendChild(actions);

    const status = element("p", "util-status");
    status.id = "utilStatus-" + toolId;
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    inputPane.appendChild(form);
    inputPane.appendChild(status);

    const resultPane = element("div", "util-pane-result");
    resultPane.setAttribute("data-util-pane", "result");

    const result = element("section", "util-result");
    result.id = "utilResult-" + toolId;
    result.hidden = false;
    const resultTitle = element("h4", "util-result-title",
      toolId === "meeting" ? t("meetingResult") : t("result"));
    const output = element("div", "util-result-output");
    output.id = "utilOutput-" + toolId;
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", t("result"));
    output.setAttribute("tabindex", "0");
    paintEmptyResult(output);

    const resultActions = element("div", "util-result-actions");
    const copyBtn = element("button", "util-result-button", t("copy"));
    copyBtn.type = "button";
    copyBtn.disabled = true;
    copyBtn.setAttribute("data-util-copy", "");
    const againBtn = element("button", "util-result-button util-result-generate", t("regenerate"));
    againBtn.type = "button";
    againBtn.disabled = true;
    againBtn.setAttribute("data-util-regenerate", "");
    resultActions.appendChild(copyBtn);
    resultActions.appendChild(againBtn);
    result.appendChild(resultTitle);
    result.appendChild(output);
    result.appendChild(resultActions);
    resultPane.appendChild(result);

    wrap.appendChild(inputPane);
    wrap.appendChild(resultPane);

    function setStatus(text, tone) {
      status.textContent = text || "";
      status.hidden = !text;
      status.setAttribute("data-tone", tone || "info");
    }

    let busy = false;
    let lastAnswer = "";

    async function runGeneration() {
      if (busy) return;
      const values = readValues(form);
      const missing = requiredKeysFor(toolId).filter((name) => !String(values[name] || "").trim());
      if (missing.length) {
        missing.forEach((name) => {
          const el = form.querySelector("#utilToolField-" + name);
          if (el) el.setAttribute("aria-invalid", "true");
        });
        setStatus(t("required"), "error");
        const first = form.querySelector("#utilToolField-" + missing[0]);
        if (first && typeof first.focus === "function") first.focus();
        return;
      }
      const prompt = toolId === "sns"
        ? contract().PROMPTS.sns(values, state.platform)
        : contract().PROMPTS[toolId](values);
      busy = true;
      primary.disabled = true;
      copyBtn.disabled = true;
      againBtn.disabled = true;
      setStatus(t("generating"), "busy");
      result.hidden = false;
      lastAnswer = "";
      output.removeAttribute("data-empty");
      output.replaceChildren();
      try {
        const answer = await contract().apiChat(prompt, toolId, (partial) => {
          lastAnswer = partial;
          renderAnswer(output, partial);
        });
        lastAnswer = answer;
        renderAnswer(output, answer);
        result.hidden = false;
        setStatus("", null);
      } catch (err) {
        setStatus(contract().errorMessage(err), "error");
        if (!String(lastAnswer || "").trim()) paintEmptyResult(output);
      } finally {
        busy = false;
        primary.disabled = false;
        const hasAnswer = Boolean(String(lastAnswer || "").trim());
        copyBtn.disabled = !hasAnswer;
        againBtn.disabled = !hasAnswer;
      }
    }

    form.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      void runGeneration();
    });
    againBtn.addEventListener("click", () => { void runGeneration(); });
    copyBtn.addEventListener("click", () => {
      const text = plainAnswer(lastAnswer).trim();
      if (!text) return;
      const copier = window.PadiemAnswerCopy && typeof window.PadiemAnswerCopy.copyText === "function"
        ? window.PadiemAnswerCopy.copyText
        : null;
      const done = (ok) => setStatus(ok ? t("copied") : t("copyFailed"), ok ? "info" : "error");
      if (copier) {
        Promise.resolve(copier(text)).then(done, () => done(false));
        return;
      }
      const nav = typeof navigator !== "undefined" ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
        Promise.resolve(nav.clipboard.writeText(text)).then(() => done(true), () => done(false));
        return;
      }
      done(false);
    });
    if (toolId === "sns") {
      state.onPlatform = (key) => {
        resultTitle.textContent = t("result") + " · " + contract().PLATFORM_TITLE[key];
      };
      resultTitle.textContent = t("result") + " · " + contract().PLATFORM_TITLE.blog;
    }
    return wrap;
  }

  let current = null;

  function mount(toolId, host) {
    const key = String(toolId || "");
    if (TOOL_KEYS.indexOf(key) < 0 || !host || typeof host.appendChild !== "function") return false;
    if (!contract()) return false;
    host.setAttribute("data-util-mounted", "form");
    const session = authSession();
    if (session && session.authenticated !== true) {
      host.appendChild(loginGate(true));
      current = { toolId: key, host: host };
      return true;
    }
    if (session === null) {
      host.appendChild(loginGate(false));
      current = { toolId: key, host: host };
      return true;
    }
    host.appendChild(buildScreen(key));
    current = { toolId: key, host: host };
    return true;
  }

  function remount() {
    if (!current || !current.host) return;
    const host = current.host;
    if (host.isConnected === false) return;
    if (typeof host.replaceChildren !== "function") return;
    host.replaceChildren();
    mount(current.toolId, host);
  }

  window.addEventListener("padiem:auth-state", remount);

  window.PadiemUtilTools = Object.freeze({
    TOOL_KEYS: TOOL_KEYS,
    mount: mount,
  });
})();
