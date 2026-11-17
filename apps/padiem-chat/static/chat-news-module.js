(() => {
  "use strict";
  // #7718 2단계 — Chat 안 '새 소식'(버전 노트). 로그인 사용자만 입구가 보이고,
  // 목록을 열면 서버가 '마지막으로 본 시각'을 기록한다. 사용자 이름은 어디에도 없다.
  const API = "/api/chat/news";
  const KINDS = { improved: "kind-improved", fixed: "kind-fixed" };
  const SOURCES = { ai_tester: "source-ai-tester", user: "source-user" };
  // #7847 — 서버가 보내는 배포 표시는 'YYYY.MM.DD' 하나뿐이다. 모양이 다른 값은
  // 목록을 버리지 않고 '그 밖의 소식'으로 묶는다.
  const VERSION = /^\d{4}\.\d{2}\.\d{2}$/;
  // Dates and descriptions below are verified milestones from the public project history.
  // Keep this list customer-facing: no internal issue numbers, account names, or test fixtures.
  const HISTORY_EVENTS = Object.freeze([
    {
      date: "2026-08-26",
      title: { ko: "Padiem Chat을 웹에서 공개했어요.", en: "Padiem Chat went live on the web." },
      detail: { ko: "질문을 입력하고 답변을 받을 수 있는 첫 화면이 열렸어요.", en: "The first public screen opened for asking questions and receiving answers." },
    },
    {
      date: "2026-09-01",
      title: { ko: "Padiem Glass 화면을 더했어요.", en: "We added the Padiem Glass look." },
      detail: { ko: "대화 글씨와 배치를 편하게 볼 수 있도록 화면 모양을 골라 쓸 수 있게 됐어요.", en: "You could choose another look for comfortable reading and conversation." },
    },
    {
      date: "2026-09-03",
      title: { ko: "답변이 완성되기 전에도 글이 이어서 보여요.", en: "Answers began appearing as they were written." },
      detail: { ko: "답변이 모두 준비될 때까지 기다리지 않아도 대화 내용을 읽을 수 있게 바꿨어요.", en: "You could start reading without waiting for the whole answer to finish." },
    },
    {
      date: "2026-09-08",
      title: { ko: "Claw와 앱 연결 메뉴가 Chat 안에 자리 잡았어요.", en: "Claw and app connections found a place in Chat." },
      detail: { ko: "대화 화면에서 Claw 작업 공간과 연결 메뉴를 바로 찾아갈 수 있어요.", en: "You could open the Claw workspace and connection menu from the chat screen." },
    },
    {
      date: "2026-09-09",
      title: { ko: "Claw 작업 결과를 저장하고 다시 열 수 있게 됐어요.", en: "Claw could save work and open it again." },
      detail: { ko: "웹에서 시작한 작업의 결과를 작업 공간에 남겨 이어서 볼 수 있어요.", en: "Results from web tasks could stay in the workspace for another visit." },
    },
    {
      date: "2026-09-11",
      title: { ko: "PDF와 Word 파일을 프로젝트에 넣고 질문할 수 있어요.", en: "You could add PDF and Word files to a project and ask about them." },
      detail: { ko: "필요한 문서를 대화에서 참고할 수 있도록 프로젝트 파일과 연결했어요.", en: "Project files became available as references in a conversation." },
    },
    {
      date: "2026-09-23",
      title: { ko: "하루·주·달 단위로 일정을 볼 수 있어요.", en: "You could view a day, week, or month of plans." },
      detail: { ko: "일정과 작업을 달력에서 날짜 범위에 맞춰 살펴볼 수 있게 됐어요.", en: "Plans and work could be explored in calendar views." },
    },
    {
      date: "2026-09-30",
      title: { ko: "Claw에서 반복 작업을 만들고 관리할 수 있어요.", en: "You could create and manage repeating Claw tasks." },
      detail: { ko: "반복할 일을 정하고 웹 화면에서 이름과 실행 시간을 바꿀 수 있게 됐어요.", en: "You could set a repeating task and change its name or schedule on the web." },
    },
    {
      date: "2026-10-02",
      title: { ko: "Google 캘린더를 연결해 일정을 읽어볼 수 있어요.", en: "You could connect Google Calendar to read your events." },
      detail: { ko: "Padiem 일정과 구분해 Google 캘린더 일정도 확인할 수 있게 됐어요.", en: "Google Calendar events could be read alongside Padiem plans." },
    },
    {
      date: "2026-10-20",
      title: { ko: "PC 연결 상태를 Chat과 Claw에서 확인할 수 있어요.", en: "You could check your PC connection in Chat and Claw." },
      detail: { ko: "연결된 PC를 알아보기 쉽도록 대화 입력창에 상태를 보여 주기 시작했어요.", en: "The composer began showing whether a PC was connected." },
    },
    {
      date: "2026-10-23",
      title: { ko: "축사·SNS 글·회의 정리 도구를 더했어요.", en: "We added tools for writing speeches, social posts, and meeting notes." },
      detail: { ko: "글쓰기와 업무 정리 도구를 메뉴에서 바로 찾을 수 있어요.", en: "Writing and work recap tools became easy to find in the menu." },
    },
    {
      date: "2026-10-23",
      title: { ko: "PDF 글자를 문서로 바꿀 수 있어요.", en: "A tool arrived to turn PDF text into a document." },
      detail: { ko: "PDF에서 글자를 꺼내 확인하고 문서로 저장할 수 있게 됐어요.", en: "You could extract text from a PDF, review it, and save it in a document." },
    },
    {
      date: "2026-10-28",
      title: { ko: "내 PC의 Excel 양식으로 견적서를 만들 수 있어요.", en: "You could create a quote with an Excel form from your PC." },
      detail: { ko: "내 PC에 있는 양식을 불러와 새 견적 문서로 이어갈 수 있게 됐어요.", en: "A form from your PC could be used to make a new quote document." },
    },
    {
      date: "2026-11-02",
      title: { ko: "PC에서 PDF를 가져와 변환한 문서를 다시 저장할 수 있어요.", en: "You could bring in a PDF from your PC and save the converted document." },
      detail: { ko: "PDF 변환 도구가 기존 PC 연결 흐름으로 이어졌어요.", en: "The PDF conversion tool joined the existing PC connection flow." },
    },
    {
      date: "2026-11-12",
      title: { ko: "내 PC의 문서를 유틸 도구로 가져올 수 있어요.", en: "You could bring documents from your PC into Utilities." },
      detail: { ko: "글을 다루는 도구에서 연결한 PC의 자료를 불러올 수 있게 됐어요.", en: "Text tools could use documents from a connected PC." },
    },
    {
      date: "2026-11-14",
      title: { ko: "Chat에서 의견을 보낼 수 있게 됐어요.", en: "You could send feedback from Chat." },
      detail: { ko: "화면에서 의견을 남기고 진행 상태를 확인할 수 있는 창구를 열었어요.", en: "A feedback space opened for sending an idea and checking its status." },
    },
    {
      date: "2026-11-15",
      title: { ko: "내 의견과 관련 새 소식을 이어 볼 수 있어요.", en: "You could follow a fixed suggestion to its related news." },
      detail: { ko: "의견을 반영해 고친 소식에서 연결된 항목을 바로 찾아갈 수 있게 됐어요.", en: "When a suggestion was addressed, its news item could be opened directly." },
    },
    {
      date: "2026-11-16",
      title: { ko: "가입 안내와 공통 약관을 로그인 흐름에 더했어요.", en: "Sign-up guidance and shared terms joined the sign-in flow." },
      detail: { ko: "만 14세 이상 확인과 개인정보 안내를 로그인 과정에서 볼 수 있어요.", en: "The sign-in flow included an age confirmation and privacy information." },
    },
    {
      date: "2026-11-16",
      title: { ko: "첫 화면과 코드 읽기 화면을 다듬었어요.", en: "We refined the first screen and code reading." },
      detail: { ko: "첫 화면 카드 설명과 코드 블록 글자가 더 잘 보이도록 손봤어요.", en: "We improved the visibility of first-screen card descriptions and code text." },
    },
    {
      date: "2026-11-16",
      title: { ko: "PDF 변환 결과와 실패 이유를 알기 쉽게 보여 줘요.", en: "PDF results and failure reasons became easier to understand." },
      detail: { ko: "변환이 끝났는지, 문제가 있었다면 어떤 이유인지 화면에서 확인할 수 있어요.", en: "You could see when conversion finished and why it failed, when it did." },
    },
  ]);
  const state = { owner: "", epoch: 0, items: [], unread: 0, loading: false, error: "", open: false, focus: 0 };
  const requests = new Set();
  let nodes, returnFocus;
  const copy = (key, values) => window.__padiemLocale?.text("news-" + key, values) || "news-" + key;
  const owner = () => {
    const auth = window.PadiemAuthSession?.get?.();
    return auth?.authenticated === true && typeof auth.ownerKey === "string" ? auth.ownerKey : "";
  };
  const current = (epoch) => epoch === state.epoch && state.owner && owner() === state.owner;
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function reset() {
    state.epoch += 1;
    for (const controller of requests) controller.abort();
    requests.clear();
    Object.assign(state, { items: [], unread: 0, loading: false, error: "", open: false, focus: 0 });
  }
  async function request(path) {
    if (!state.owner || owner() !== state.owner) return null;
    const epoch = state.epoch, controller = new AbortController();
    requests.add(controller);
    const init = { method: "GET", credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: "application/json" } };
    try {
      const response = await window.fetch(path, init);
      const data = await response.json().catch(() => null);
      if (!current(epoch)) return null;
      if (response.status === 401) { state.owner = ""; reset(); paint(); return null; }
      return { status: response.status, data };
    } catch (_) {
      return current(epoch) ? { status: 0, data: null } : null;
    } finally { requests.delete(controller); }
  }
  function item(value) {
    if (!value || !Number.isInteger(value.number) || value.number < 1
        || typeof value.kind !== "string" || !KINDS[value.kind]
        || typeof value.title !== "string" || typeof value.detail !== "string"
        || typeof value.source !== "string" || !(value.source in SOURCES || value.source === "none")
        || typeof value.published_at !== "string") return null;
    return { number: value.number, kind: value.kind, title: value.title, detail: value.detail,
      source: value.source, published_at: value.published_at,
      version: typeof value.version === "string" && VERSION.test(value.version) ? value.version : "" };
  }
  const date = (value) => {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleDateString(document.documentElement.lang === "en" ? "en" : "ko") : "";
  };
  const historyDate = (value) => {
    const [year, month, day] = value.split("-").map(Number);
    if (![year, month, day].every(Number.isInteger)) return value;
    return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(
      document.documentElement.lang === "en" ? "en" : "ko-KR",
      { timeZone: "UTC", year: "numeric", month: "numeric", day: "numeric" },
    );
  };
  function historyRow(entry) {
    const li = element("li", "news-item news-history-item");
    li.dataset.historyDate = entry.date;
    const heading = element("div", "news-item-heading");
    const time = element("time", "news-date", historyDate(entry.date));
    time.setAttribute("datetime", entry.date);
    const language = document.documentElement.lang === "en" ? "en" : "ko";
    heading.append(time);
    li.append(heading, element("h3", "news-title", entry.title[language]),
      element("p", "news-detail", entry.detail[language]));
    return li;
  }
  function paintHistory() {
    const entries = [...HISTORY_EVENTS].sort((left, right) => left.date.localeCompare(right.date));
    nodes.historyList.replaceChildren(...entries.map(historyRow));
    const empty = entries.length === 0;
    nodes.historyStatus.hidden = !empty;
    nodes.historyStatus.textContent = empty ? copy("history-empty") : "";
  }
  // The source label is bundled: consecutive items that share one source
  // carry it only on the last row of the run, so a batch does not repeat the
  // label on every line.
  const lastOfRun = (items) => items.map((entry, index) => {
    const next = items[index + 1];
    return Boolean(SOURCES[entry.source]) && (!next || next.source !== entry.source);
  });
  function row(entry, active, showSource) {
    const li = element("li", "news-item");
    li.dataset.newsNumber = String(entry.number);
    if (active) li.dataset.active = "true";
    const heading = element("div", "news-item-heading");
    heading.append(element("span", "news-kind " + (entry.kind === "fixed" ? "news-kind-fixed" : "news-kind-improved"), copy(KINDS[entry.kind])));
    const when = date(entry.published_at);
    if (when) heading.append(element("span", "news-date", when));
    li.append(heading, element("h3", "news-title", entry.title), element("p", "news-detail", entry.detail));
    if (showSource) li.append(element("small", "news-source", copy(SOURCES[entry.source])));
    return li;
  }
  // #7847 — 같은 배포에서 낸 소식은 그 배포 제목 아래에 모으고, 배포 표시가 없는
  // 소식은 마지막 '그 밖의 소식'에 모은다. 배포는 최신이 먼저다.
  function groups(items) {
    const order = [];
    const buckets = new Map();
    for (const entry of items) {
      if (!buckets.has(entry.version)) { buckets.set(entry.version, []); order.push(entry.version); }
      buckets.get(entry.version).push(entry);
    }
    order.sort((left, right) => (!left ? 1 : !right ? -1 : right.localeCompare(left)));
    return order.map((version) => ({ version, items: buckets.get(version) }));
  }
  function listRows() {
    const lines = [];
    for (const group of groups(state.items)) {
      const heading = element("li", "news-group");
      heading.append(element("h3", "news-group-title", group.version
        ? copy("version", { version: group.version }) : copy("other")));
      lines.push(heading);
      const runs = lastOfRun(group.items);
      lines.push(...group.items.map((entry, index) => row(entry, state.focus === entry.number, runs[index])));
    }
    return lines;
  }
  function paint() {
    if (!nodes) return;
    const signedIn = Boolean(state.owner);
    nodes.button.hidden = !signedIn;
    const unseen = signedIn && state.unread > 0;
    nodes.dot.hidden = !unseen;
    nodes.dotText.hidden = !unseen;
    if (unseen) nodes.dotText.textContent = copy("unread-notice");
    nodes.button.setAttribute("aria-expanded", String(state.open && nodes.dialog.open));
    if (state.open) {
      nodes.list.replaceChildren(...listRows());
      nodes.status.textContent = state.error ? copy(state.error)
        : state.loading ? copy("loading")
        : state.items.length ? "" : copy("empty");
      nodes.list.setAttribute("aria-busy", String(state.loading));
      paintHistory();
    }
  }
  async function refreshUnread() {
    if (!state.owner || state.open) return;
    const epoch = state.epoch;
    const reply = await request(API + "/unread");
    if (!reply || !current(epoch) || state.open) return;
    state.unread = reply.status === 200 && reply.data?.ok === true
      && Number.isInteger(reply.data.unread_count) ? Math.max(0, reply.data.unread_count) : 0;
    paint();
  }
  async function load() {
    if (state.loading || !state.owner) return;
    state.loading = true; state.error = ""; paint();
    const epoch = state.epoch;
    const reply = await request(API);
    if (!reply || !current(epoch)) return;
    state.loading = false;
    if (reply.status === 200 && reply.data?.ok === true && Array.isArray(reply.data.news)) {
      state.items = reply.data.news.map(item).filter(Boolean);
      // Opening the list has just marked it seen on the server; the dot goes away.
      state.unread = 0;
    } else {
      state.error = "failed";
    }
    paint();
    if (state.focus) {
      const target = nodes.list.querySelector?.(`[data-news-number="${state.focus}"]`);
      if (target?.scrollIntoView) target.scrollIntoView({ block: "start" });
    }
  }
  async function open(focusNumber = 0) {
    const who = owner();
    if (!who) return;
    if (who !== state.owner) { state.owner = who; reset(); }
    state.focus = Number.isInteger(focusNumber) && focusNumber > 0 ? focusNumber : 0;
    state.open = true;
    returnFocus = document.activeElement;
    if (typeof nodes.dialog.showModal === "function") nodes.dialog.showModal(); else nodes.dialog.setAttribute("open", "");
    nodes.button.setAttribute("aria-expanded", "true");
    paint();
    await load();
    (state.focus ? nodes.list : nodes.close).focus?.();
  }
  function close() {
    if (nodes.dialog.open && typeof nodes.dialog.close === "function") nodes.dialog.close();
    else { nodes.dialog.removeAttribute("open"); closed(); }
  }
  function closed() {
    state.open = false;
    nodes.button.setAttribute("aria-expanded", "false");
    if (returnFocus?.isConnected !== false) returnFocus?.focus?.();
  }
  function sync() {
    const next = owner();
    if (next === state.owner) return;
    state.owner = next;
    const wasOpen = state.open;
    reset();
    if (wasOpen && nodes.dialog.open) { nodes.dialog.removeAttribute("open"); }
    state.open = false;
    paint();
    if (next) void refreshUnread();
  }
  function init() {
    const ids = { button: "newsButton", dot: "newsDot", dotText: "newsDotText", dialog: "newsDialog",
      close: "newsClose", list: "newsList", status: "newsStatus", historyList: "newsHistoryList",
      historyStatus: "newsHistoryStatus" };
    nodes = Object.fromEntries(Object.entries(ids).map(([key, id]) => [key, document.getElementById(id)]));
    if (Object.values(nodes).some((node) => !node)) return;
    nodes.button.addEventListener("click", () => void open());
    nodes.close.addEventListener("click", close);
    nodes.dialog.addEventListener("close", closed);
    window.addEventListener("padiem:auth-state", sync);
    window.addEventListener("padiem:localechange", paint);
    window.addEventListener("pagehide", () => { state.owner = ""; reset(); });
    window.addEventListener("pageshow", sync);
    window.PadiemNews = {
      open: (focusNumber) => { void open(Number.isInteger(focusNumber) && focusNumber > 0 ? focusNumber : 0); },
    };
    paint();
    sync();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
