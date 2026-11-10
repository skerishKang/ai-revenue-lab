/*
 * #7173 PR2 · Util tools inside the Util app (#util/speech, #util/sns,
 * #util/meeting).
 *
 * File boundary: the screens live here (and in util-tools.css); the prompt
 * shapes, the same-origin /api/chat/stream call and the failure copy live in
 * util-tools-contract.js. util-app.js owns the routes and the shell; app.js
 * stays the Chat navigation bridge and gains nothing (R5 #7216).
 *
 * The browser never leaves this screen: no council-app link, no Claw
 * conversation, no second store. Copy goes through the shared Chat/Claw
 * clipboard module (shared-answer-copy.js).
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

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key) {
    const table = T[lang()] || T.ko;
    return table[key] !== undefined ? table[key] : T.ko[key];
  }

  function contract() {
    return window.PadiemUtilContract || null;
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // The screen paints light markdown; the copy button hands over the plain
  // projection (util-tools-markdown.js). A missing module leaves both paths on
  // the raw text rather than printing a broken page.
  function renderAnswer(host, value) {
    const markdown = window.PadiemUtilMarkdown;
    if (markdown && typeof markdown.render === "function") {
      markdown.render(host, value);
      return;
    }
    host.textContent = value;
  }

  function plainAnswer(value) {
    const markdown = window.PadiemUtilMarkdown;
    return markdown && typeof markdown.plain === "function"
      ? markdown.plain(value)
      : String(value == null ? "" : value);
  }

  // ── session ──────────────────────────────────────────────────────────────

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
      // The Chat shell owns the sign-in dialog; the util screen never sends the
      // visitor to another page.
      const button = document.getElementById("loginButton");
      if (button && typeof button.click === "function") button.click();
    });
    gate.appendChild(login);
    return gate;
  }

  // ── form ─────────────────────────────────────────────────────────────────

  function field(name, labelText, type, required, placeholder, rows) {
    const label = element("label", "util-field");
    label.appendChild(element("span", "util-field-label", labelText));
    let input;
    if (type === "textarea") {
      input = element("textarea", "util-input");
      input.rows = rows || 3;
    } else if (type === "select") {
      input = element("select", "util-input");
    } else {
      input = element("input", "util-input");
      input.type = type;
    }
    input.name = name;
    input.id = "utilToolField-" + name;
    label.setAttribute("for", input.id);
    if (required) input.required = true;
    if (placeholder) input.placeholder = placeholder;
    label.appendChild(input);
    return { label: label, input: input };
  }

  function selectField(name, labelText, options, selected) {
    const built = field(name, labelText, "select", false, "");
    options.forEach((option) => {
      const node = element("option", null, option[1]);
      node.value = option[0];
      node.selected = option[0] === selected;
      built.input.appendChild(node);
    });
    return built;
  }

  const SPEECH_FIELDS = [
    ["event", "행사명", "text", true, "예: 제78주년 광복절 기념식"],
    ["audience", "참석 대상", "text", false, "예: 지역 주민 200명"],
    ["author", "직책과 이름", "text", false, "예: 지역구 국회의원 김의민"],
  ];
  const SPEECH_MORE = [
    ["date", "행사 날짜", "date", false, ""],
    ["place", "장소", "text", false, "예: 시청 대강당"],
    ["nature", "행사 성격", "text", false, "예: 지역 행사"],
    ["message", "주요 메시지", "textarea", false, "예: 함께 성장하는 지역사회"],
    ["emphasis", "강조 내용", "textarea", false, "예: 상생과 배려"],
  ];
  const SNS_FIELDS = [
    ["event", "행사명", "text", true, "예: 주민 정원 사업 설명회"],
    ["whenwhere", "날짜·장소", "text", false, "예: 10월 30일 오후 2시, 구청 소회의실"],
    ["content", "주요 내용", "textarea", true, "예: 정원 사업 신청 방법과 지원 금액 안내"],
    ["audience", "대상 독자", "text", false, "예: 구내 상인"],
    ["memo", "메모", "textarea", false, "예: 참석자에게 강조할 한 가지"],
  ];
  const MEETING_FIELDS = [
    ["title", "회의명", "text", true, "예: 10월 주민 민원 회의"],
    ["when", "회의 일시", "datetime-local", false, ""],
    ["attendees", "참석자", "text", false, "예: 비서실장, 지역 담당"],
    ["content", "회의 내용", "textarea", true, "회의에서 오간 내용을 그대로 적어 주세요"],
  ];
  const REQUIRED_FIELDS = Object.freeze({
    speech: ["event"], sns: ["event", "content"], meeting: ["title", "content"],
  });

  function addField(form, spec, rows) {
    form.appendChild(field(spec[0], spec[1], spec[2], spec[3], spec[4], rows).label);
  }

  function buildSpeechForm(form) {
    SPEECH_FIELDS.forEach((spec) => addField(form, spec));
    form.appendChild(selectField("length", "분량", [["short", "1분"], ["medium", "3분"], ["long", "5분"]], "medium").label);
    const more = element("details", "util-more");
    more.appendChild(element("summary", "util-more-summary", t("more")));
    const body = element("div", "util-more-body");
    SPEECH_MORE.forEach((spec) => addField(body, spec, spec[2] === "textarea" ? 3 : 0));
    body.appendChild(selectField("tone", "말투", [["formal", "공식"], ["warm", "따뜻한"], ["concise", "간결"]], "formal").label);
    body.appendChild(field("style", "기존 축사 샘플 (말투 반영)", "textarea", false, "기존 축사/인사말 원문 붙여넣기", 4).label);
    more.appendChild(body);
    form.appendChild(more);
  }

  function buildSnsForm(form, state) {
    SNS_FIELDS.forEach((spec) => addField(form, spec, spec[2] === "textarea" ? 4 : 0));
    form.appendChild(selectField("tone", "문체",
      [["casual", "캐주얼"], ["professional", "전문적"], ["emotional", "감성적"]], "professional").label);
    const tabs = element("div", "util-platform-tabs");
    tabs.setAttribute("role", "group");
    tabs.setAttribute("aria-label", t("platformGroup"));
    const holder = element("div", "util-field util-field-tabs");
    Object.keys(contract().PLATFORM_TITLE).forEach((key) => {
      const button = element("button", "util-platform-tab", contract().PLATFORM_TITLE[key]);
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
    form.appendChild(holder);
  }

  function buildMeetingForm(form) {
    MEETING_FIELDS.forEach((spec) => addField(form, spec, spec[2] === "textarea" ? 8 : 0));
  }

  function readValues(form) {
    const values = {};
    Array.prototype.forEach.call(form.querySelectorAll("[name]"), (input) => {
      values[input.name] = typeof input.value === "string" ? input.value.trim() : "";
    });
    return values;
  }

  // ── screen ───────────────────────────────────────────────────────────────

  function generateLabel(toolId) {
    if (toolId === "speech") return t("speechGenerate");
    return toolId === "sns" ? t("snsGenerate") : t("meetingGenerate");
  }

  function buildScreen(toolId) {
    const state = { platform: "blog", onPlatform: null };
    const wrap = element("div", "util-tool-form");
    wrap.setAttribute("data-util-form", toolId);
    const form = element("form", "util-form");
    form.id = "utilToolForm-" + toolId;
    form.noValidate = true;
    if (toolId === "speech") buildSpeechForm(form);
    else if (toolId === "sns") buildSnsForm(form, state);
    else buildMeetingForm(form);

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

    const result = element("section", "util-result");
    result.id = "utilResult-" + toolId;
    result.hidden = true;
    const resultTitle = element("h4", "util-result-title",
      toolId === "meeting" ? t("meetingResult") : t("result"));
    const output = element("div", "util-result-output");
    output.id = "utilOutput-" + toolId;
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", t("result"));
    output.setAttribute("tabindex", "0");
    const resultActions = element("div", "util-result-actions");
    const copyBtn = element("button", "util-result-button", t("copy"));
    copyBtn.type = "button";
    copyBtn.setAttribute("data-util-copy", "");
    const againBtn = element("button", "util-result-button util-result-generate", t("regenerate"));
    againBtn.type = "button";
    againBtn.setAttribute("data-util-regenerate", "");
    resultActions.appendChild(copyBtn);
    resultActions.appendChild(againBtn);
    result.appendChild(resultTitle);
    result.appendChild(output);
    result.appendChild(resultActions);

    wrap.appendChild(form);
    wrap.appendChild(status);
    wrap.appendChild(result);

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
      const missing = (REQUIRED_FIELDS[toolId] || []).filter((name) => !String(values[name] || "").trim());
      if (missing.length) {
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
        if (!String(lastAnswer || "").trim()) result.hidden = true;
      } finally {
        busy = false;
        primary.disabled = false;
        copyBtn.disabled = false;
        againBtn.disabled = false;
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

  // ── mount (called by util-app.js) ────────────────────────────────────────

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
