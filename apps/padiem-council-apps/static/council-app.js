/*
 * PADIEM 의원3종 — council apps modules (one IIFE, three independent tools).
 *
 * Shared contract layer + three product modules (speech / sns / meeting).
 * The shared layer re-states the SAME shipped contracts as the original
 * util-menu.js (apps/padiem-chat/static/util-menu.js, after PR #5916):
 *
 *   - generation:  POST /api/chat {messages:[{role:"user",content}],
 *     mode:"auto", tier, util:"speech"|"sns"|"meeting"}. The util scope is
 *     the #5916 routing label that keeps a declared utility out of the
 *     shared native-calendar branch (a meeting text containing
 *     확인/추가/일정 must reach the model, not the calendar clarify);
 *     unknown scopes are refused server-side before any model call. tier
 *     comes from window.PadiemTierSelection when it returns one of
 *     free/plus/pro/max/admin, otherwise "free". No timezone, no
 *     calendar_turn_id.
 *   - storage:     /api/projects, /api/projects/{pid}/files (text/plain JSON
 *     writes; details read back via data.file.content)
 *   - session:     cookie credentials on every call ("include"), signed-in
 *     state read from GET /api/auth/status (fail-closed gate like
 *     councillor.js: the tools stay locked until authenticated === true).
 *     A signed-out visit logs in INSIDE this page through the existing
 *     POST /api/auth/password/login credential contract (#5942); the visitor is
 *     never sent to the Chat home page, and the Google route is a plain link
 *     that returns to this entry through the server's signed state.
 *
 * Nothing here calls /api/b66*, /api/claw*, /auth/* POST routes or any other
 * path, and no second authority, store or model lane is introduced. The
 * three tools never reference each other, so each can ship as its own
 * product later; the entry page merely hosts all three.
 *
 * SNS photo storage: the #5728 composition contract (LOCAL 1) already
 * lives on main (PR #5924). This module deliberately does NOT copy it —
 * text drafts only. Connecting the stored-photo composition through an
 * adapter is separate follow-up work; the seam is this module's sns
 * builder plus the README boundary note.
 */
(() => {
  "use strict";

  // ── shared contract layer (same shape as util-menu.js 12-140) ────────────

  // ── #6046 콘텐츠 국가 ─────────────────────────────────────────────────
  // 국가는 **출력 언어와 표현**을 고르는 라벨이다(법적 관할·데이터 거주지 아님).
  // kr 은 지시문이 비어 있어 프롬프트가 지금과 문자 단위로 같고, 요청에도 country 를 싣지 않는다.
  const COUNTRY_KEY = "padiem-council-country";
  const COUNTRY_INSTRUCTIONS = Object.freeze({
    kr: "",
    us: "\n\nWrite the entire answer in natural English (US conventions). " +
        "Keep every personal name, date, place and amount exactly as given. " +
        "Do not invent a named member, a real person's activity, or an event that was not provided.",
    uk: "\n\nWrite the entire answer in natural English with British spelling and UK conventions. " +
        "Keep every personal name, date, place and amount exactly as given. " +
        "Do not invent a named member, a real person's activity, or an event that was not provided.",
    fr: "\n\nRédigez toute la réponse en français naturel. " +
        "Conservez exactement les noms, dates, lieux et montants fournis. " +
        "N'inventez ni élu nommé, ni activité, ni événement non fournis.",
  });
  function currentCountry() {
    try {
      const value = (window.localStorage && window.localStorage.getItem(COUNTRY_KEY)) || "";
      return Object.prototype.hasOwnProperty.call(COUNTRY_INSTRUCTIONS, value) ? value : "kr";
    } catch (_) { return "kr"; }
  }
  function countryInstruction(country) {
    return COUNTRY_INSTRUCTIONS[country] || "";
  }

  async function apiChat(prompt, util) {
    // Same rule as util-menu.js apiChat / app.js selectedProductTier().
    // The util scope (PR #5916 contract) is the request's routing label:
    // it keeps a declared utility out of the shared native-calendar branch
    // (including try_native_calendar_chat's own second classification) and
    // the server refuses unknown scopes before any model call. It grants no
    // identity, tier, entitlement or tool scope and is not an auth input.
    const selected = window.PadiemTierSelection?.get?.();
    const tier = ["free", "plus", "pro", "max", "admin"].includes(selected) ? selected : "free";
    const country = currentCountry();
    const content = prompt + countryInstruction(country);
    const payload = { messages: [{ role: "user", content: content }], mode: "auto", tier };
    if (util) payload.util = util;
    // 계약: 값이 없으면 kr 이므로, kr 요청은 지금과 같은 본문을 보낸다(하위 호환).
    if (country !== "kr") payload.country = country;
    const res = await fetch("/api/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      if (res.status === 401) markSessionLost();
      const message = data?.error?.message;
      throw new Error(typeof message === "string" && message ? message : "HTTP " + res.status);
    }
    const data = await res.json();
    return (data && data.answer) ? data.answer : (data && data.message ? data.message : JSON.stringify(data));
  }

  async function getProjects() {
    const res = await fetch("/api/projects", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.projects) ? data.projects : [];
  }

  async function ensureProject() {
    const projects = await getProjects();
    if (projects.length) return projects[0].id;
    const res = await fetch("/api/projects", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "내 프로젝트" }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.project ? data.project.id : null;
  }

  async function saveProjectFile(pid, name, text, mediaType) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign(
        { name: name, media_type: mediaType || "text/plain", text: text },
        currentCountry() === "kr" ? {} : { country: currentCountry() },
      )),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.file ? data.file : null;
  }

  async function listProjectFiles(pid) {
    const res = await fetch("/api/projects/" + pid + "/files", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.files) ? data.files : [];
  }

  async function fetchProjectFile(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId), { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json();
    const content = data && data.file && (data.file.content || data.file.text);
    return typeof content === "string" ? content : null;
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // Project id per tool module; each module keeps its own handle exactly like
  // the original per-tool closures, so tools stay independent.
  function projectHandle() {
    let currentPid = null;
    return {
      get() { return currentPid; },
      async ensure() { if (!currentPid) currentPid = await ensureProject(); return currentPid; },
    };
  }

  // #5728 binary photo upload — the SAME project-file channel as text
  // drafts (original bytes, owner/project scoped). Ported from the merged
  // #5924 contract so the council app's SNS composition stores real files,
  // not copies of LOCAL 1 code paths.
  async function uploadProjectImage(pid, file) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": encodeURIComponent(file.name),
        "X-Padiem-Media-Type": file.type,
      },
      body: file,
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data && data.file ? data.file : null;
  }

  async function deleteProjectFile(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId), {
      method: "DELETE",
      credentials: "include",
    });
    return res.ok || res.status === 404;
  }

  async function fetchOriginalDataUrl(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId) + "/original", {
      credentials: "include",
    });
    if (!res.ok) return null;
    const blob = await res.blob();
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  }

  // ── one file-name rule for the four stored document families (#5942) ──────
  // A book is a derived product, not a meeting record, and a draft SNS post is
  // not a speech manuscript. The prefixes below are the ones the Chat util
  // already writes (#5608), so a book saved from either surface lists in both;
  // no new store, table or media type is introduced.
  const BOOK_PREFIX = "활동집 - ";
  const SNS_POST_SUFFIX = "게시글.txt";
  const SNS_ROSTER_NAME = "SNS 사진 구성.json";

  function storedName(file) { return String((file && file.name) || ""); }
  function isStoredBook(file) { return storedName(file).startsWith(BOOK_PREFIX); }
  function isSnsPostFile(file) {
    const name = storedName(file);
    return name.endsWith(SNS_POST_SUFFIX) && !isStoredBook(file);
  }
  function isSnsRosterFile(file) { return storedName(file) === SNS_ROSTER_NAME; }
  /** Plain manuscripts: neither a book, an SNS post draft nor the photo roster. */
  // #6046 — 저장 문서의 국가가 선택 국가와 같은 것만 보인다.
  // 컬럼이 없는 기존 문서는 kr 로 읽어 한국어를 선택한 사용자 화면이 비지 않는다.
  function sameCountry(file) {
    return String((file && file.country) || "kr") === currentCountry();
  }

  function isManuscriptFile(file) {
    const name = storedName(file);
    return name.endsWith(".txt") && !isStoredBook(file) && !isSnsPostFile(file);
  }
  /** The book file name comes from the draft's own first line, so an edited
   *  title re-saves under the edited name; unsafe characters are dropped. */
  function bookFileName(text) {
    const firstLine = String(text || "").split("\n", 1)[0].replace(/^[0-9]+\.\s*/, "").trim();
    const safe = firstLine.replace(/[\\/:*?"<>|]/g, "").replace(/\.*$/, "").slice(0, 40).trim();
    return BOOK_PREFIX + (safe || "제목 미정") + ".txt";
  }

  // ── speech module (prompt template ported verbatim from util-menu.js) ────

  function buildSpeechPrompt(form) {
    const d = new FormData(form);
    const event = (d.get("event") || "").trim();
    const date = (d.get("date") || "").trim();
    const place = (d.get("place") || "").trim();
    const nature = (d.get("nature") || "").trim();
    const audience = (d.get("audience") || "").trim();
    const author = (d.get("author") || "").trim();
    const message = (d.get("message") || "").trim();
    const emphasis = (d.get("emphasis") || "").trim();
    const length = d.get("length") || "medium";
    const tone = d.get("tone") || "formal";
    const style = (d.get("style") || "").trim();
    const lengthMap = { short: "짧게(300자 내외)", medium: "보통(600자 내외)", long: "길게(1000자 내외)" };
    const toneMap = { formal: "공식적이고 격식 있는", warm: "따뜻하고 친근한", concise: "간결하고 명료한" };
    let prompt = "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.\n\n";
    prompt += `행사명: ${event}\n`;
    if (date) prompt += `행사 날짜: ${date}\n`;
    if (place) prompt += `장소: ${place}\n`;
    if (nature) prompt += `행사 성격: ${nature}\n`;
    if (audience) prompt += `참석 대상: ${audience}\n`;
    if (author) prompt += `작성자/직책: ${author}\n`;
    if (message) prompt += `주요 메시지: ${message}\n`;
    if (emphasis) prompt += `강조 내용: ${emphasis}\n`;
    prompt += `분량: ${lengthMap[length] || "보통"}\n`;
    prompt += `말투: ${toneMap[tone] || "공식적"}\n`;
    if (style) prompt += `\n아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:\n---\n${style}\n---\n`;
    prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
    return prompt;
  }

  const speechModule = (() => {
    const projects = projectHandle();

    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilSpeechForm";
      const fieldsets = [
        ["기본 정보", [
          ["event", "행사명", "text", true],
          ["date", "행사 날짜", "date", false],
          ["place", "장소", "text", false],
          ["nature", "행사 성격", "text", false],
          ["audience", "참석 대상", "text", false],
          ["author", "작성자/직책", "text", false],
        ]],
        ["내용", [
          ["message", "주요 메시지", "textarea", false],
          ["emphasis", "강조 내용", "textarea", false],
        ]],
      ];
      fieldsets.forEach(([legend, fields]) => {
        const fs = el("fieldset", "council-fieldset");
        fs.appendChild(el("legend", null, legend));
        fields.forEach(([name, label, type, req]) => {
          const l = el("label", null, label + " ");
          let field;
          if (type === "textarea") {
            field = document.createElement("textarea");
            field.name = name;
            field.rows = name === "message" ? 3 : 2;
          } else {
            field = document.createElement("input");
            field.name = name;
            field.type = type;
          }
          if (req) field.required = true;
          l.appendChild(field);
          fs.appendChild(l);
        });
        form.appendChild(fs);
      });
      const fsTone = el("fieldset", "council-fieldset");
      fsTone.appendChild(el("legend", null, "분량·말투·참고"));
      const lengthLabel = el("label", null, "분량 ");
      const lengthSel = document.createElement("select");
      lengthSel.name = "length";
      [["short", "짧게"], ["medium", "보통"], ["long", "길게"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "medium") o.selected = true;
        lengthSel.appendChild(o);
      });
      lengthLabel.appendChild(lengthSel);
      fsTone.appendChild(lengthLabel);
      const toneLabel = el("label", null, "말투 ");
      const toneSel = document.createElement("select");
      toneSel.name = "tone";
      [["formal", "공식"], ["warm", "따뜻한"], ["concise", "간결"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "formal") o.selected = true;
        toneSel.appendChild(o);
      });
      toneLabel.appendChild(toneSel);
      fsTone.appendChild(toneLabel);
      const styleLabel = el("label", null, "기존 축사 샘플 (말투 반영) ");
      const styleTa = document.createElement("textarea");
      styleTa.name = "style";
      styleTa.rows = 4;
      styleTa.placeholder = "기존 축사/인사말 원문 붙여넣기";
      styleLabel.appendChild(styleTa);
      fsTone.appendChild(styleLabel);
      form.appendChild(fsTone);

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "초안 생성");
      submitBtn.type = "submit";
      const saveBtn = el("button", "council-save", "저장");
      saveBtn.type = "button";
      saveBtn.id = "councilSpeechSave";
      formActions.append(submitBtn, saveBtn);
      form.appendChild(formActions);
      host.appendChild(form);

      const result = el("div", "council-result");
      result.id = "councilSpeechResult";
      result.hidden = true;
      result.appendChild(el("h3", null, "생성 결과"));
      const output = document.createElement("textarea");
      output.id = "councilSpeechOutput";
      output.rows = 12;
      result.appendChild(output);
      const actions = el("div", "council-actions");
      const copyBtn = el("button", null, "복사");
      copyBtn.type = "button";
      copyBtn.id = "councilSpeechCopy";
      const dlBtn = el("button", null, "TXT 다운로드");
      dlBtn.type = "button";
      dlBtn.id = "councilSpeechDownload";
      actions.append(copyBtn, dlBtn);
      result.appendChild(actions);
      host.appendChild(result);

      // #5731 contract: the stored speech history is listed on tool re-entry
      // too (not only right after a save), and each row carries a “참고로
      // 선택” action that fills the style sample textarea with the stored
      // body — the next generation fences it as the sample, like a pasted
      // one. Reuse of the existing owner/project files, no second store.
      const savedList = el("div", "council-saved-list");
      savedList.id = "councilSpeechSaved";
      host.appendChild(savedList);

      async function refreshSpeechList() {
        const pid = await projects.ensure();
        if (!pid) return;
        const files = await listProjectFiles(pid);
         const speechFiles = files.filter(isManuscriptFile).filter(sameCountry);
        savedList.replaceChildren();
        savedList.appendChild(el("h3", null, "저장된 축사 원고"));
        if (!speechFiles.length) {
          savedList.appendChild(el("p", "council-empty", "저장된 축사가 없습니다."));
          return;
        }
        const ul = document.createElement("ul");
        speechFiles.forEach((f) => {
          const li = document.createElement("li");
          li.className = "council-saved-item";
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "council-saved-open";
          btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
          btn.addEventListener("click", async () => {
            const content = await fetchProjectFile(pid, f.id);
            if (typeof content === "string") {
              output.value = content;
              result.hidden = false;
            } else {
              alert("저장된 축사의 본문을 읽을 수 없습니다.");
            }
          });
          li.appendChild(btn);
          const useAsRef = document.createElement("button");
          useAsRef.type = "button";
          useAsRef.className = "council-speech-use-ref";
          useAsRef.dataset.fileId = f.id;
          useAsRef.textContent = "참고로 선택";
          useAsRef.addEventListener("click", async () => {
            const styleField = form.querySelector("[name=style]");
            if (!styleField) { alert("참고 원고 필드를 찾을 수 없습니다."); return; }
            const res = await fetch("/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
            if (!res.ok) { alert("참고 원고를 불러오지 못했습니다."); return; }
            const data = await res.json().catch(() => null);
            const content = data && data.file && (data.file.content || data.file.text);
            if (typeof content !== "string" || !content.trim()) { alert("참고 원고의 본문을 읽을 수 없습니다."); return; }
            styleField.value = content;
          });
          li.appendChild(useAsRef);
          ul.appendChild(li);
        });
        savedList.appendChild(ul);
      }

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(buildSpeechPrompt(form), "speech"); }
        catch (err) { output.value = "생성 실패: " + (err && err.message ? err.message : err); }
      });
      copyBtn.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyBtn.textContent = "복사됨"; setTimeout(() => { copyBtn.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlBtn.addEventListener("click", () => { downloadText(output.value, "speech.txt"); });
      saveBtn.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        const pid = await projects.ensure();
        if (!pid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (form.querySelector("[name=event]")?.value || "축사").trim() + ".txt";
        const file = await saveProjectFile(pid, name, text);
        if (file) {
          saveBtn.textContent = "저장됨";
          setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
          await refreshSpeechList();
        } else {
          alert("저장 실패");
        }
      });
      // Re-entry lists the stored history too (#5731).
      refreshSpeechList();
      onCountryChange(refreshSpeechList);
    }

    return { build(host) { buildForm(host); }, buildPrompt: buildSpeechPrompt };
  })();

  // ── sns module (prompt template ported verbatim from util-menu.js) ───────
  // Photo composition connected through the merged #5728/#5924 contract:
  // binary originals upload via the SAME project-file channel as text
  // drafts, one version-2 roster JSON carries the order/positions/saved
  // draft/platform, and re-entry restores the composition ONCE at build
  // time. No LOCAL 1 code is copied — the storage contract is the shipped
  // PADIEM one, re-stated against this app's own DOM.

  function buildSnsPrompt(form, platform, photos) {
    const d = new FormData(form);
    const event = (d.get("event") || "").trim();
    const whenwhere = (d.get("whenwhere") || "").trim();
    const content = (d.get("content") || "").trim();
    const memo = (d.get("memo") || "").trim();
    const audience = (d.get("audience") || "").trim();
    const tone = d.get("tone") || "professional";
    const toneMap = { casual: "캐주얼하고 친근한", professional: "전문적이고 신뢰감 있는", emotional: "감성적이고 따뜻한" };
    const platformGuide = {
      blog: "블로그 게시글: 800-1200자, 제목 포함, 소제목 구분, 상세한 설명",
      facebook: "페이스북 게시글: 300-500자, 친근한 톤, 이모지 적절히, 해시태그 3-5개",
      instagram: "인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부",
    };
    let prompt = `다음 행사 정보를 바탕으로 ${platformGuide[platform]}을 작성해 주세요.\n\n`;
    prompt += `행사명: ${event}\n`;
    if (whenwhere) prompt += `날짜·장소: ${whenwhere}\n`;
    prompt += `주요 내용: ${content}\n`;
    if (photos && photos.length) {
      const names = photos.map((ph) => ph.name).join(", ");
      prompt += `첨부 사진: ${photos.length}장 (${names})\n`;
      prompt += platform === "blog"
        ? "사진은 본문 문단 사이에 삽입됩니다. 각 사진이 어느 내용과 이어지는지 참고해서 문단을 구성해 주세요.\n"
        : "사진은 본문과 구분된 게시물 미디어로 첨부됩니다. 본문에 이미지 위치 설명은 넣지 마세요.\n";
    }
    if (memo) prompt += `메모: ${memo}\n`;
    if (audience) prompt += `대상 독자: ${audience}\n`;
    prompt += `문체: ${toneMap[tone]}\n`;
    prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
    return prompt;
  }

  const snsModule = (() => {
    const projects = projectHandle();

    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilSnsForm";
      const fields = [
        ["event", "행사명", "text", true],
        ["whenwhere", "날짜·장소", "text", false],
        ["content", "주요 내용", "textarea", true],
        ["memo", "메모", "textarea", false],
        ["audience", "대상 독자", "text", false],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        let field;
        if (type === "textarea") {
          field = document.createElement("textarea");
          field.name = name;
          field.rows = name === "content" ? 3 : 2;
        } else {
          field = document.createElement("input");
          field.name = name;
          field.type = "text";
        }
        if (req) field.required = true;
        l.appendChild(field);
        form.appendChild(l);
      });
      const toneLabel = el("label", null, "문체 ");
      const toneSel = document.createElement("select");
      toneSel.name = "tone";
      [["casual", "캐주얼"], ["professional", "전문적"], ["emotional", "감성적"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "professional") o.selected = true;
        toneSel.appendChild(o);
      });
      toneLabel.appendChild(toneSel);
      form.appendChild(toneLabel);

      const tabDiv = el("div", "council-sns-tabs");
      const tabNames = { blog: "블로그", facebook: "페이스북", instagram: "인스타그램" };
      let platform = "blog";
      Object.keys(tabNames).forEach((key) => {
        const b = el("button", "council-sns-tab" + (key === "blog" ? " active" : ""), tabNames[key]);
        b.type = "button";
        b.dataset.platform = key;
        b.addEventListener("click", () => {
          tabDiv.querySelectorAll(".council-sns-tab").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          platform = key;
          title.textContent = tabNames[key] + " 게시글";
          renderPhotoList();
          renderPreview();
        });
        tabDiv.appendChild(b);
      });
      form.appendChild(tabDiv);

      // #5728: photo composition replaces the old direct photo-URL field.
      // Photos are picked locally (multiple, image/*), previewed as
      // thumbnails, removable and re-orderable. Blog places each photo
      // between chosen paragraphs; facebook/instagram treat them as
      // separate post media. Photos survive platform switches.
      const photos = [];
      let photoSeq = 0;
      const photoBox = el("div", "council-photos");
      photoBox.id = "councilSnsPhotoBox";
      const photoHead = el("div", "council-photos-head");
      const photoTitle = el("span", "council-photos-title", "사진");
      const photoAdd = el("button", "council-photo-add", "사진 추가");
      photoAdd.type = "button";
      photoAdd.id = "councilSnsPhotoAdd";
      const photoInput = document.createElement("input");
      photoInput.type = "file";
      photoInput.accept = "image/png,image/jpeg,image/webp";
      photoInput.multiple = true;
      photoInput.hidden = true;
      photoInput.id = "councilSnsPhotoInput";
      const photoCount = el("span", "council-photos-count", "0장");
      photoCount.id = "councilSnsPhotoCount";
      photoHead.append(photoTitle, photoAdd, photoInput, photoCount);
      const photoList = el("ul", "council-photo-list");
      photoList.id = "councilSnsPhotoList";
      const photoNote = el("p", "council-photo-note");
      photoNote.id = "councilSnsPhotoNote";
      photoBox.append(photoHead, photoList, photoNote);
      form.appendChild(photoBox);

      function photoNoteText() {
        if (platform === "blog") return "블로그는 각 사진을 본문 문단 사이에 삽입합니다. 미리보기에서 위치를 확인하세요.";
        if (platform === "instagram") return "인스타그램은 사진을 별도 미디어로 첨부합니다(이미지 중심 미리보기).";
        return "페이스북은 사진을 본문과 구분된 게시물 미디어로 첨부합니다.";
      }

      function readPhotoFile(file) {
        return new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve({ id: ++photoSeq, name: file.name, dataUrl: String(reader.result || ""), position: "auto" });
          reader.onerror = () => resolve(null);
          reader.readAsDataURL(file);
        });
      }

      // #5728: the roster is one small JSON file that carries the whole
      // persisted composition — the photo order, the blog insertion
      // positions, the saved draft text and the platform it was written
      // for (version 2). The photo originals themselves are already stored
      // (each add uploaded them). Rewrites replace the previous roster in
      // place, so a stale roster can never resurrect a photo the owner
      // deleted.
      const PHOTO_ROSTER_NAME = "SNS 사진 구성.json";
      // The last explicitly saved draft rides every roster rewrite, so a
      // later photo change never silently drops the saved text.
      let lastSavedDraft = null;
      // Roster writes serialize: two changes landing together must never
      // leave two roster files behind (an older one would win a name lookup
      // and silently revert the newer order or position).
      let rosterWriteChain = Promise.resolve();
      function writePhotoRoster(pid, savedDraft) {
        if (!pid) return;
        const carriedDraft = savedDraft === undefined ? lastSavedDraft : savedDraft;
        rosterWriteChain = rosterWriteChain.then(async () => {
          const roster = { version: 2, photos: photos
            .map((p) => ({ fileId: String(p.id), name: p.name, position: p.position })) };
          // The saved draft rides with the roster so re-entry restores the
          // text too; the last explicit 저장 wins.
          if (carriedDraft && carriedDraft.text) {
            roster.draft = { text: carriedDraft.text, platform: carriedDraft.platform || platform };
          }
          const existing = await listProjectFiles(pid);
          const previous = existing.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (previous) await deleteProjectFile(pid, previous.id);
          await saveProjectFile(pid, PHOTO_ROSTER_NAME, JSON.stringify(roster), "application/json");
        }).catch(() => { /* the composition keeps working; the roster stays last-known */ });
        return rosterWriteChain;
      }

      function renderPhotoList() {
        photoCount.textContent = photos.length + "장";
        photoNote.textContent = photoNoteText();
        photoList.replaceChildren();
        photos.forEach((item) => {
          const li = el("li", "council-photo-item");
          const img = document.createElement("img");
          img.className = "council-photo-thumb";
          img.src = item.dataUrl;
          img.alt = item.name;
          const nameSpan = el("span", "council-photo-name", item.name);
          const controls = el("div", "council-photo-controls");
          if (platform === "blog") {
            const posLabel = el("label", "council-photo-pos", "삽입 위치 ");
            const sel = document.createElement("select");
            sel.className = "council-photo-pos-select";
            sel.dataset.photoId = String(item.id);
            const opts = [["auto", "자동"], ["0", "맨 앞"], ["end", "문단 끝"]];
            opts.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); });
             sel.value = item.position;
             sel.addEventListener("change", async () => { item.position = sel.value; renderPreview(); await writePhotoRoster(projects.get()); });
            posLabel.appendChild(sel);
            controls.appendChild(posLabel);
          }
          const up = el("button", "council-photo-move", "↑"); up.type = "button"; up.dataset.move = "-1"; up.dataset.photoId = String(item.id);
          const down = el("button", "council-photo-move", "↓"); down.type = "button"; down.dataset.move = "1"; down.dataset.photoId = String(item.id);
          const del = el("button", "council-photo-remove", "삭제"); del.type = "button"; del.dataset.photoId = String(item.id); del.dataset.action = "remove";
          controls.append(up, down, del);
          li.append(img, nameSpan, controls);
          photoList.appendChild(li);
        });
      }

      photoList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!target || !target.dataset) return;
        // Stored photos carry server ids like "file_<hex>"; local-only rows
        // carry numeric ids. Compare as strings so both resolve.
        const id = String(target.dataset.photoId);
        const index = photos.findIndex((p) => String(p.id) === id);
        if (index < 0) return;
        if (target.dataset.move) {
          const to = index + Number(target.dataset.move);
          if (to < 0 || to >= photos.length) return;
          const [moved] = photos.splice(index, 1);
          photos.splice(to, 0, moved);
        } else if (target.dataset.action === "remove") {
          const pid = projects.get();
          if (photos[index].id && pid) {
            const gone = await deleteProjectFile(pid, photos[index].id);
            if (!gone) { alert("사진 삭제 실패: " + photos[index].name); return; }
          }
          photos.splice(index, 1);
        } else {
          return;
        }
         renderPhotoList();
         renderPreview();
         // Every durable composition change (reorder and removal here,
         // insertion positions on the selects) rewrites the roster file, so
         // the order and the blog insertion positions outlive the session.
         await writePhotoRoster(projects.get());
       });

      photoAdd.addEventListener("click", () => photoInput.click());
      photoInput.addEventListener("change", async () => {
        const files = Array.from(photoInput.files || []);
        const failed = [];
        for (const file of files) {
          if (!file || String(file.type || "").indexOf("image/") !== 0) continue;
          // A photo joins the composition only once the project-file upload
          // succeeded — the thumbnail and the stored original are the same
          // bytes, and a failed upload never looks "saved".
          const pid = await projects.ensure();
          if (!pid) { failed.push(file.name); continue; }
          const stored = await uploadProjectImage(pid, file);
          if (!stored) { failed.push(file.name); continue; }
          const item = await readPhotoFile(file);
          if (item) { item.id = stored.id; photos.push(item); }
        }
        if (failed.length) alert("사진 저장 실패: " + failed.join(", "));
        photoInput.value = "";
        renderPhotoList();
        renderPreview();
        // An added photo is part of the durable composition as soon as its
        // upload landed — the roster records it right away.
        if (!failed.length) await writePhotoRoster(projects.get());
      });

      function blogParagraphs(text) {
        return String(text || "").split(new RegExp("\\n\\s*\\n")).filter((p) => p.trim());
      }

      function interleaveBlog(text) {
        const parts = blogParagraphs(text);
        if (!photos.length) return parts.map((p) => ({ type: "text", value: p }));
        const out = [];
        if (photos.some((p) => p.position === "0")) {
          photos.filter((p) => p.position === "0").forEach((p) => out.push({ type: "photo", value: p }));
        }
        parts.forEach((para, i) => {
          out.push({ type: "text", value: para });
          photos.forEach((p) => {
            if (p.position === "auto") { if (i === Math.min(photos.indexOf(p), Math.max(parts.length - 1, 0))) out.push({ type: "photo", value: p }); }
            else if (p.position === "end") { if (i === parts.length - 1) out.push({ type: "photo", value: p }); }
            else if (String(i + 1) === String(p.position)) { out.push({ type: "photo", value: p }); }
          });
        });
        return out;
      }

      function renderPreview() {
        const box = previewBox;
        if (!box || box.hidden) return;
        box.replaceChildren();
        const text = output.value || "";
        if (platform === "blog") {
          interleaveBlog(text).forEach((seg) => {
            if (seg.type === "text") { const p = el("p", "council-preview-para", seg.value); box.appendChild(p); }
            else { const im = document.createElement("img"); im.className = "council-preview-photo"; im.src = seg.value.dataUrl; im.alt = seg.value.name; box.appendChild(im); }
          });
        } else {
          if (text.trim()) { const p = el("p", "council-preview-para", text); box.appendChild(p); }
          const grid = el("div", "council-sns-media-grid" + (platform === "instagram" ? " insta" : ""));
          photos.forEach((ph) => { const im = document.createElement("img"); im.src = ph.dataUrl; im.alt = ph.name; grid.appendChild(im); });
          box.appendChild(grid);
        }
        const note = el("p", "council-photo-note", "미리보기는 초안 구성 확인용입니다. 실제 SNS 자동 게시 기능이 아닙니다.");
        box.appendChild(note);
      }

      renderPhotoList();

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "생성");
      submitBtn.type = "submit";
      const saveBtn = el("button", "council-save", "저장");
      saveBtn.type = "button";
      saveBtn.id = "councilSnsSave";
      formActions.append(submitBtn, saveBtn);
      form.appendChild(formActions);

      const result = el("div", "council-result");
      result.id = "councilSnsResult";
      result.hidden = true;
      const title = el("h3", null, "블로그 게시글");
      title.id = "councilSnsTitle";
      const output = document.createElement("textarea");
      output.id = "councilSnsOutput";
      output.rows = 12;
      const previewBox = el("div", "council-sns-preview");
      previewBox.id = "councilSnsPreview";
      previewBox.hidden = true;
      const actions = el("div", "council-actions");
      const copyB = el("button", null, "복사");
      copyB.type = "button";
      copyB.id = "councilSnsCopy";
      const dlB = el("button", null, "TXT 다운로드");
      dlB.type = "button";
      dlB.id = "councilSnsDownload";
      actions.append(copyB, dlB);
      result.append(title, output, previewBox, actions);

      host.replaceChildren(form, result);

      // #5728: re-entry restores the persisted composition ONCE, at build
      // time — before any interaction with the photo list. The stored image
      // files are the originals; when the roster file exists it fixes the
      // order and the blog insertion positions, and photos it does not
      // mention still surface after it so nothing the owner stored
      // vanishes. A roster that carries a saved draft (version 2) also
      // restores the draft text and switches to the platform it was saved
      // under.
      (async () => {
        try {
          const pid = await projects.ensure();
          if (!pid) return;
          const files = await listProjectFiles(pid);
          const imageFiles = files.filter((f) => f.media_type === "image/png"
            || f.media_type === "image/jpeg" || f.media_type === "image/webp");
          let order = null;
          let savedDraft = null;
          const rosterFile = files.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (rosterFile) {
            const detailRes = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(rosterFile.id), { credentials: "include" });
            if (detailRes.ok) {
              const detail = await detailRes.json().catch(() => null);
              try {
                const roster = JSON.parse(String((detail && detail.file && detail.file.content) || ""));
                if (roster && Array.isArray(roster.photos)) order = roster.photos;
                // A saved draft is part of the same roster record; a v1
                // roster (photos only) leaves the draft area untouched.
                if (roster && roster.draft && typeof roster.draft.text === "string" && roster.draft.text.trim()) {
                  savedDraft = roster.draft;
                }
              } catch (_) { /* unreadable roster falls back to the stored order */ }
            }
          }
          if (savedDraft) {
            // The draft comes back with the platform it was written for;
            // photos restore after this so the preview is coherent. It also
            // rides future roster rewrites, so a later photo change never
            // silently drops the saved text.
            lastSavedDraft = savedDraft;
            result.hidden = false;
            output.value = savedDraft.text;
            previewBox.hidden = false;
            if (savedDraft.platform && savedDraft.platform !== platform) {
              const targetTab = Array.from(tabDiv.querySelectorAll(".council-sns-tab")).find((t) => t.dataset.platform === savedDraft.platform);
              if (targetTab) targetTab.click();
              else { platform = savedDraft.platform; title.textContent = ({ blog: "블로그", facebook: "페이스북", instagram: "인스타그램" })[savedDraft.platform] + " 게시글"; }
            }
          }
          if (photos.length || !imageFiles.length) {
            if (savedDraft) renderPreview();
            return;
          }
          const ordered = [];
          if (order && order.length) {
            order.forEach((entry) => {
              const meta = imageFiles.find((f) => f.id === (entry && entry.fileId));
              if (meta) ordered.push({ meta: meta, position: entry && typeof entry.position === "string" && entry.position ? entry.position : "auto" });
            });
            imageFiles.forEach((meta) => {
              if (!ordered.some((o) => o.meta.id === meta.id)) ordered.push({ meta: meta, position: "auto" });
            });
          } else {
            imageFiles.forEach((meta) => ordered.push({ meta: meta, position: "auto" }));
          }
          for (const entry of ordered) {
            const dataUrl = await fetchOriginalDataUrl(pid, entry.meta.id);
            if (!dataUrl) continue;
            photos.push({ id: entry.meta.id, name: entry.meta.name, dataUrl: dataUrl, position: entry.position });
          }
          renderPhotoList();
          renderPreview();
        } catch (_) { /* restore is best effort; an empty composition stays honest */ }
      })();

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(buildSnsPrompt(form, platform, photos), "sns"); }
        catch (err) { output.value = "생성 실패: " + (err && err.message ? err.message : err); }
        previewBox.hidden = false;
        renderPreview();
      });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "sns-" + platform + ".txt"); });
      saveBtn.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        const pid = await projects.ensure();
        if (!pid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (title.textContent || "sns").trim() + ".txt";
        const file = await saveProjectFile(pid, name, text);
        if (file) {
          saveBtn.textContent = "저장됨";
          setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
          // The saved draft rides in the roster so re-entry restores the
          // text and its platform, not only the photos.
           lastSavedDraft = { text: text, platform: platform };
           await writePhotoRoster(pid, lastSavedDraft);
        } else {
          alert("저장 실패");
        }
      });
    }

    return { build(host) { buildForm(host); }, buildPrompt: buildSnsPrompt };
  })();

  // ── meeting module (prompts ported verbatim from util-menu.js) ───────────

  function buildMeetingPrompt(form) {
    const d = new FormData(form);
    const title = (d.get("title") || "").trim();
    const when = (d.get("when") || "").trim();
    const attendees = (d.get("attendees") || "").trim();
    const content = (d.get("content") || "").trim();
    let prompt = "다음 회의 내용을 정리해 주세요.\n\n";
    prompt += `회의명: ${title}\n`;
    if (when) prompt += `회의 일시: ${when}\n`;
    if (attendees) prompt += `참석자: ${attendees}\n`;
    prompt += `회의 내용:\n${content}\n\n`;
    prompt += "다음 항목으로 정리해 주세요:\n1. 회의 요약 (3-5문장)\n2. 주요 논의사항 (bullet)\n3. 결정사항 (bullet)\n4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n5. 미해결 사항";
    return prompt;
  }

  function buildBookPrompt(contents) {
    let prompt = "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n";
    prompt += contents.join("\n\n") + "\n\n";
    prompt += "위 기록을 바탕으로 다음을 생성해 주세요:\n";
    prompt += "1. 책/활동집 제목 후보 3개\n";
    prompt += "2. 목차 (5-8장)\n";
    prompt += "3. 각 장별 원고 초안 (200-400자)\n";
    prompt += "4. 마무리 인사\n\n";
    prompt += "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요. 근거가 있는 내용과 제안/해석을 구분하세요. 각 장 끝에 근거가 된 기록 파일명을 표시하세요.";
    return prompt;
  }

  const meetingModule = (() => {
    const projects = projectHandle();

    function buildForm(host) {
      const form = el("form", "council-form");
      form.id = "councilMeetingForm";
      const fields = [
        ["title", "회의명", "text", true],
        ["when", "회의 일시", "datetime-local", false],
        ["attendees", "참석자", "text", false],
        ["content", "회의 내용", "textarea", true],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        let field;
        if (type === "textarea") {
          field = document.createElement("textarea");
          field.name = name;
          field.rows = name === "content" ? 6 : 2;
        } else {
          field = document.createElement("input");
          field.name = name;
          field.type = type;
        }
        if (req) field.required = true;
        l.appendChild(field);
        form.appendChild(l);
      });

      const formActions = el("div", "council-form-actions");
      const submitBtn = el("button", "council-generate", "요약 생성");
      submitBtn.type = "submit";
      const formSaveB = el("button", "council-save", "저장");
      formSaveB.type = "button";
      formSaveB.id = "councilMeetingSave";
      formActions.append(submitBtn, formSaveB);
      form.appendChild(formActions);

      const result = el("div", "council-result");
      result.id = "councilMeetingResult";
      result.hidden = true;
      result.appendChild(el("h3", null, "회의 요약"));
      const output = document.createElement("textarea");
      output.id = "councilMeetingOutput";
      output.rows = 12;
      result.appendChild(output);
      const actions = el("div", "council-actions");
      const copyB = el("button", null, "복사");
      copyB.type = "button";
      copyB.id = "councilMeetingCopy";
      const dlB = el("button", null, "TXT 다운로드");
      dlB.type = "button";
      dlB.id = "councilMeetingDownload";
      actions.append(copyB, dlB);
      result.appendChild(actions);

      const archive = el("div", "council-archive");
      archive.id = "councilMeetingArchive";

      host.replaceChildren(form, result, archive);

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(buildMeetingPrompt(form), "meeting"); }
        catch (err) { output.value = "생성 실패: " + (err && err.message ? err.message : err); }
      });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "meeting.txt"); });
      formSaveB.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        const pid = await projects.ensure();
        if (!pid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (form.querySelector("[name=title]")?.value || "회의").trim() + ".txt";
        const file = await saveProjectFile(pid, name, text);
        if (file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          await refreshArchive(archive);
        } else {
          alert("저장 실패");
        }
      });

      async function refreshArchive(arc) {
        const pid = await projects.ensure();
        if (!pid) return;
        const files = await listProjectFiles(pid);
        // A book is not one of its own source records, and an SNS draft or the
        // photo roster never belongs here either.
        const meetingFiles = files.filter(isManuscriptFile).filter(sameCountry);
        const bookFiles = files.filter(isStoredBook);

        // The book editor is built before the lists are drawn: a stored book has
        // to reopen into it even when no record exists in this project yet.
        const bookResult = el("div", "council-result");
        bookResult.id = "councilBookResult";
        bookResult.hidden = true;
        bookResult.appendChild(el("h3", null, "책/활동집 초안"));
        const bookOutput = document.createElement("textarea");
        bookOutput.id = "councilBookOutput";
        bookOutput.rows = 16;
        bookResult.appendChild(bookOutput);
        const bookActions = el("div", "council-actions");
        const bookCopy = el("button", null, "복사");
        bookCopy.type = "button";
        const bookDl = el("button", null, "TXT 다운로드");
        bookDl.type = "button";
        const bookSave = el("button", "council-save", "활동집 저장");
        bookSave.type = "button";
        bookSave.id = "councilBookSave";
        bookActions.append(bookCopy, bookDl, bookSave);
        bookResult.appendChild(bookActions);

        const bookBtn = el("button", "council-generate", "선택 기록으로 책/활동집 초안 생성");
        bookBtn.type = "button";
        bookBtn.id = "councilBookGenerate";

        arc.replaceChildren();
        arc.appendChild(el("h3", null, "활동 기록"));
        if (!meetingFiles.length) {
          arc.appendChild(el("p", "council-empty", "저장된 회의 기록이 없습니다."));
        } else {
          arc.appendChild(bookBtn);
          const ul = document.createElement("ul");
          meetingFiles.forEach((f) => {
            const li = document.createElement("li");
            li.className = "council-archive-item";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = f.id;
            cb.className = "council-book-check";
            cb.setAttribute("aria-label", f.name + " 책/활동집에 포함");
            /* 상자는 24px(#6075)로 두고, 그 주먹을 44×44 라벨로 감싼다. 라벨이 입력을
               감싸면 상자 밖을 눌러도 선택되므로 이름·본문 단추와 경쟁하지 않는다. */
            const check = document.createElement("label");
            check.className = "council-archive-check";
            check.appendChild(cb);
            li.appendChild(check);
            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const content = await fetchProjectFile(pid, f.id);
              if (typeof content === "string") {
                output.value = content;
                result.hidden = false;
              } else {
                alert("저장된 회의 기록의 본문을 읽을 수 없습니다.");
              }
            });
            li.appendChild(btn);
            ul.appendChild(li);
          });
          arc.appendChild(ul);
        }
        arc.appendChild(bookResult);

        bookBtn.addEventListener("click", async () => {
          const checked = Array.from(document.querySelectorAll(".council-book-check:checked"));
          if (!checked.length) { alert("선택된 기록이 없습니다."); return; }
          bookResult.hidden = false;
          bookOutput.value = "선택한 회의 기록을 불러오는 중...";
          try {
            const contents = [];
            for (const checkbox of checked) {
              const file = meetingFiles.find((item) => item.id === checkbox.value);
              if (!file) continue;
              const res = await fetch("/api/projects/" + encodeURIComponent(pid) + "/files/" + encodeURIComponent(file.id), { credentials: "include" });
              if (!res.ok) throw new Error("선택한 회의 기록을 불러오지 못했습니다: " + file.name);
              const data = await res.json();
              if (!data || !data.file || typeof data.file.content !== "string" || !data.file.content.trim()) {
                throw new Error("선택한 회의 기록의 본문이 비어 있거나 올바르지 않습니다: " + file.name);
              }
              contents.push("[기록: " + data.file.name + "]\n" + data.file.content);
            }
            bookOutput.value = "생성 중...";
            bookOutput.value = await apiChat(buildBookPrompt(contents), "meeting");
          } catch (e) {
            bookOutput.value = "생성 실패: " + (e && e.message ? e.message : e);
          }
        });
        bookCopy.addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(bookOutput.value); bookCopy.textContent = "복사됨"; setTimeout(() => { bookCopy.textContent = "복사"; }, 1500); } catch (_) {}
        });
        bookDl.addEventListener("click", () => { downloadText(bookOutput.value, "book.txt"); });

        // The draft is a product, not scratch: it persists through the same
        // project-file channel under the book name rule. One press must never
        // create two copies, so the button is armed only while nothing is in
        // flight and the list is refreshed from the server afterwards.
        let bookSaving = false;
        bookSave.addEventListener("click", async () => {
          const text = bookOutput.value.trim();
          if (!text || bookSaving) return;
          bookSaving = true;
          bookSave.disabled = true;
          bookSave.textContent = "저장 중…";
          let saved = null;
          try {
            saved = await saveProjectFile(pid, bookFileName(text), text);
          } finally {
            bookSaving = false;
            bookSave.disabled = false;
          }
          if (!saved) {
            bookSave.textContent = "활동집 저장";
            alert("활동집 저장 실패");
            return;
          }
          // The list is refreshed from the server, which rebuilds the archive -
          // including this editor - so the draft the user just saved is written
          // back and the confirmation lands on the node that is actually on screen.
          await refreshArchive(arc);
          const current = document.getElementById("councilBookOutput");
          const currentResult = document.getElementById("councilBookResult");
          const currentSave = document.getElementById("councilBookSave") || bookSave;
          if (current && currentResult) {
            current.value = text;
            currentResult.hidden = false;
          }
          currentSave.textContent = "저장됨";
          setTimeout(() => { currentSave.textContent = "활동집 저장"; }, 1500);
          const opened = (arc.querySelectorAll(".council-book-open") || [])
            .find((b) => String(b.textContent).indexOf(saved.name) === 0);
          if (opened) opened.setAttribute("aria-current", "true");
        });

        if (bookFiles.length) {
          const bookSec = el("div", "council-book-list");
          bookSec.appendChild(el("h3", null, "저장된 활동집"));
          const bookUl = document.createElement("ul");
          bookFiles.forEach((f) => {
            const li = document.createElement("li");
            li.className = "council-archive-item";
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "council-book-open";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const content = await fetchProjectFile(pid, f.id);
              if (typeof content !== "string") {
                alert("저장된 활동집의 본문을 읽을 수 없습니다.");
                return;
              }
              bookResult.hidden = false;
              bookOutput.value = content;
              if (typeof bookOutput.focus === "function") bookOutput.focus();
            });
            li.appendChild(btn);
            bookUl.appendChild(li);
          });
          bookSec.appendChild(bookUl);
          arc.appendChild(bookSec);
        }
      }

      // The archive and the stored-book list load when the tool opens, the same
      // way the speech list does and the way util-menu.js does it: a re-entry
      // must show what is already stored before anything is saved again.
      refreshArchive(archive);
      onCountryChange(() => refreshArchive(archive));

      return { refreshArchive };
    }

    return {
      build(host) { buildForm(host); },
      buildPrompt: buildMeetingPrompt,
      buildBookPrompt,
    };
  })();

  // #6065: the stored lists are country-scoped by sameCountry(), but they were only
  // ever re-filtered when a tool rebuilt them. Switching the content country left the
  // previous country's documents on screen until a save or a reload. Each list scope
  // registers its own refresher here, so the control that changes the generation
  // language also refreshes what it claims is stored for that language.
  function onCountryChange(refresh) {
    const select = host("councilCountry");
    if (select) select.addEventListener("change", refresh);
  }

  function syncCountrySelect() {
    const select = host("councilCountry");
    if (!select) return;
    const country = currentCountry();
    select.value = country;
    // init()(평소 로드)과 enterSignedIn()(로그인 후) 이 모두 부른다. 리스너는 한 번만 건다.
    if (session.countryBound) return;
    session.countryBound = true;
    select.addEventListener("change", () => {
      const next = COUNTRY_INSTRUCTIONS[select.value] === undefined ? "kr" : select.value;
      try { if (window.localStorage) window.localStorage.setItem(COUNTRY_KEY, next); } catch (_) {}
      setStatus(next === "kr" ? "" : "생성 결과의 언어가 바뀝니다(저장 문서는 그대로).");
    });
  }

  // ── independent entry wiring: auth gate, then build all three tools ──────

  async function readAuthStatusOnce() {
    const res = await fetch("/api/auth/status", {
      credentials: "include",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      // #6127: a 5xx is the server failing to answer, not a verdict about this
      // visitor. Chat draws the same line for the runtime's NoGilError race
      // (#5479), where every dynamic route can 500 while the account itself is
      // untouched. 401/403 IS such a verdict about the visitor, so it is returned
      // quietly and never re-asked.
      if (res.status >= 500) throw new Error("auth status unavailable");
      return { signedIn: false, methods: null, unavailable: false };
    }
    const data = await res.json().catch(() => null);
    if (!data) throw new Error("auth status unavailable");
    return {
      signedIn: !!(data && data.authenticated === true),
      methods: (data && data.methods) || null,
      unavailable: false,
    };
  }

  // #6114 as solved for Chat: a Python Worker restart can eat one status read, so
  // a request that produced NO answer is re-asked ONCE before the page says the
  // state cannot be determined. Measured on production, one re-ask takes the
  // "cannot tell" rate from 30% of loads to 10%; a definitive answer is never
  // re-asked, so a signed-out visitor pays one round trip, not two.
  async function checkSignedIn() {
    let outcome = null;
    for (let attempt = 0; attempt < 2 && !outcome; attempt += 1) {
      try {
        outcome = await readAuthStatusOnce();
      } catch (_) {
        outcome = null;
      }
    }
    // fail-closed gate, unchanged from councillor.js: nothing is attached unless
    // the server itself says this cookie is authenticated, and an unanswered read
    // is not permission.
    return outcome || { signedIn: false, methods: null, unavailable: true };
  }

  // ── session and selection state (this page's UI state, never an authority) ──
  // The three cards are the entry: one chosen tool, one panel. A signed-out visit
  // logs in here (the existing same-origin session contract), then continues into
  // the tool it had picked. No new endpoint, store, token or account system.
  const TOOLS = Object.freeze(["speech", "sns", "meeting"]);
  const LABELS = Object.freeze({ speech: "축사·인사말", sns: "SNS 홍보", meeting: "회의정리·활동집" });
  const session = { signedIn: false, built: false, bound: false, selected: null, pending: null,
                     unavailable: false, themeBound: false };
  let bodies = {};

  function host(id) { return document.getElementById(id); }
  function setBadge(text) { const node = host("councilAuthBadge"); if (node) { node.textContent = text; node.hidden = true; } }
  function setStatus(text) {
    const node = host("councilAuthStatus");
    if (!node) return;
    node.textContent = text || "";
    node.hidden = !text;
  }
  function showAuthPanel(message, badge) {
    const panel = host("councilAuthPanel");
    if (panel) panel.hidden = false;
    const action = host("councilAuthAction");
    if (action) action.hidden = false;
    setBadge(badge || "로그인 필요");
    if (message) setStatus(message);
  }
  function hideAuthPanel() {
    const panel = host("councilAuthPanel");
    if (panel) panel.hidden = true;
    const action = host("councilAuthAction");
    if (action) action.hidden = true;
    setStatus("");
  }

  function store() {
    // A host may refuse storage (private mode, and the module harness runs this
    // file with no storage at all). Selection then lives in the URL only.
    try { return window.localStorage || null; } catch (_) { return null; }
  }
  function rememberedTool() {
    try {
      const value = store() && store().getItem("padiem-council-tool");
      return TOOLS.indexOf(value) >= 0 ? value : null;
    } catch (_) { return null; }
  }
  function rememberTool(tool) {
    try { if (store()) store().setItem("padiem-council-tool", tool); } catch (_) {}
  }
  function toolFromUrl() {
    const hash = (window.location && window.location.hash) || "";
    const value = hash.replace(/^#\/?/, "");
    return TOOLS.indexOf(value) >= 0 ? value : null;
  }
  function writeToolToUrl(tool) {
    const history = window.history;
    if (!tool || !history || typeof history.replaceState !== "function") return;
    try { history.replaceState(null, "", "#/" + tool); } catch (_) {}
  }

  function cardButtons() {
    return Array.from(document.querySelectorAll(".council-card-select"));
  }

  function focusToolPanel(tool) {
    const body = bodies[tool];
    const field = body ? body.querySelector("input") : null;
    if (field && typeof field.focus === "function") field.focus();
    const section = host("council-" + tool);
    if (section && typeof section.scrollIntoView === "function") {
      try { section.scrollIntoView({ block: "start" }); } catch (_) {}
    }
  }

  function applySelection(tool, moveFocus) {
    session.selected = tool;
    TOOLS.forEach((key) => {
      const body = bodies[key];
      if (body) body.hidden = key !== tool;
      const section = host("council-" + key);
      if (section && section.classList) section.classList[ key === tool ? "add" : "remove"]("active");
    });
    cardButtons().forEach((button) => {
      const active = button.dataset.tool === tool;
      button.setAttribute("aria-expanded", active ? "true" : "false");
      if (button.classList) button.classList[active ? "add" : "remove"]("active");
      const label = LABELS[button.dataset.tool] || "";
      button.textContent = active ? "닫기" : "열기";
      button.setAttribute("aria-label", label + " " + (active ? "닫기" : "열기"));
    });
    if (tool) {
      rememberTool(tool);
      writeToolToUrl(tool);
      if (moveFocus) focusToolPanel(tool);
    }
    paintWorkspace(tool || null);
    return session.selected;
  }

  function openLoginHere(tool, message) {
    if (tool) session.pending = tool;
    // #6127: "로그인이 필요합니다"는 서버가 답하지 못했을 때 잘못된 지시입니다.
    // 게이트는 그대로 닫혀 있습니다.
    if (session.unavailable && !message) {
      showAuthPanel("로그인 상태 확인에 실패했습니다. 다시 시도해 주세요.", "로그인 확인 실패");
      return;
    }
    showAuthPanel(message || (!session.signedIn && session.pending
      ? "로그인이 필요합니다. 선택한 업무(" + LABELS[session.pending] + ")는 로그인 후 이 화면에서 바로 이어집니다."
      : ""));
    const form = host("councilLoginForm");
    const field = form ? form.querySelector("[name=identifier]") : null;
    if (field && typeof field.focus === "function") field.focus();
  }

  function bindCards() {
    if (session.bound) return;
    cardButtons().forEach((button) => {
      button.addEventListener("click", () => {
        const tool = button.dataset.tool;
        if (!session.signedIn) { openLoginHere(tool); return; }
        applySelection(session.selected === tool ? null : tool, true);
      });
    });
    const action = host("councilAuthAction");
    if (action) action.addEventListener("click", () => openLoginHere(session.selected));
  }

  function offerGoogle(methods) {
    const row = host("councilGoogleRow");
    if (row) row.hidden = !(methods && methods.google === true);
  }

  async function loginWithPassword(form) {
    const identifier = form.querySelector("[name=identifier]");
    const password = form.querySelector("[name=password]");
    const submit = form.querySelector(".council-login");
    setStatus("로그인 중…");
    if (submit) submit.disabled = true;
    let outcome = { ok: false, message: "로그인하지 못했습니다. 다시 시도해 주세요." };
    try {
      // The EXISTING PADIEM credential contract: same-origin JSON, host-only
      // session cookie, one non-disclosing failure projection.
      const res = await fetch("/api/auth/password/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: identifier ? identifier.value : "",
          password: password ? password.value : "",
        }),
      });
      const data = await res.json().catch(() => null);
      const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "";
      outcome = { ok: res.ok, message: res.ok ? "" : (message || "이메일 또는 비밀번호가 올바르지 않습니다.") };
    } catch (_) {
      outcome = { ok: false, message: "로그인하지 못했습니다. 네트워크를 확인해 주세요." };
    }
    if (submit) submit.disabled = false;
    if (!outcome.ok) {
      setStatus(outcome.message);
      if (password) password.value = "";
      return false;
    }
    if (password) password.value = "";
    await enterSignedIn();
    return true;
  }

  async function enterSignedIn() {
    const auth = await checkSignedIn();
    session.signedIn = auth.signedIn;
    session.unavailable = !!auth.unavailable;
    if (!session.signedIn) { showAuthPanel("로그인 상태 확인에 실패했습니다. 다시 시도해 주세요."); return false; }
    setBadge("로그인됨");
    hideAuthPanel();
    syncCountrySelect();
    // syncCountrySelect sets the value without dispatching, so the pills follow it here.
    applyTheme(selectedCountry(), theme.style);
    buildToolPanels();
    const wanted = session.pending || toolFromUrl() || rememberedTool();
    const focusWanted = Boolean(session.pending);
    session.pending = null;
    applySelection(TOOLS.indexOf(wanted) >= 0 ? wanted : null, focusWanted);
    return true;
  }

  function buildToolPanels() {
    if (session.built) return;
    const tools = { speech: speechModule, sns: snsModule, meeting: meetingModule };
    TOOLS.forEach((key) => {
      const hostNode = bodies[key];
      if (hostNode && tools[key]) tools[key].build(hostNode);
    });
    session.built = true;
  }

  function bindAuthForm() {
    const form = host("councilLoginForm");
    if (!form || form.dataset.councilBound === "1") return;
    form.dataset.councilBound = "1";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await loginWithPassword(form);
    });
  }

  function markSessionLost() {
    if (!session.signedIn) return false;
    session.signedIn = false;
    openLoginHere(session.selected, "세션이 만료되었습니다. 다시 로그인하면 이 화면에서 이어나갑니다.");
    return true;
  }

  // ── 디자인 축: 국가 4 · 스타일 5 ───────────────────────────────────────
  // The two axes come from the #5967 정본 and stay as independent as it defines them: the
  // country picks the tone ramp and the photography, the style picks where that material is
  // used. 4 x 5 is therefore 4 + 5 CSS blocks, and the browser can reach all twenty.
  //
  // Neither axis becomes a new authority over data. The country still belongs to
  // #councilCountry, so the existing change listeners keep filtering the saved lists and the
  // archive and keep writing padiem-council-country; the pills above it are a mirror. The
  // style is the only new value and it gets its own key, beside padiem-council-country and
  // padiem-council-tool rather than replacing either.
  const DESIGN_COUNTRIES = Object.freeze(["kr", "us", "uk", "fr"]);
  const DESIGN_STYLES = Object.freeze(["classic", "modern", "dark", "light", "minimal"]);
  const COUNTRY_NAMES = Object.freeze({ kr: "한국", us: "미국", uk: "영국", fr: "프랑스" });
  const STYLE_NAMES = Object.freeze({ classic: "클래식", modern: "모던", dark: "다크", light: "라이트", minimal: "미니멀" });
  const theme = { country: "kr", style: "light", open: false };

  function rememberedStyle() {
    try {
      const value = store() && store().getItem("padiem-council-style");
      return DESIGN_STYLES.indexOf(value) >= 0 ? value : "light";
    } catch (_) { return "light"; }
  }
  function rememberStyle(style) {
    try { if (store()) store().setItem("padiem-council-style", style); } catch (_) {}
  }
  function selectedCountry() {
    const node = host("councilCountry");
    const value = node && node.value;
    return DESIGN_COUNTRIES.indexOf(value) >= 0 ? value : "kr";
  }
  function markGroup(group, attr, value) {
    if (!group || typeof group.querySelectorAll !== "function") return;
    // attribute-only: the only elements inside a group carrying the axis attribute are
    // its radios, and the harness resolves one selector token, not a compound.
    Array.from(group.querySelectorAll("[" + attr + "]")).forEach((button) => {
      const on = button.getAttribute(attr) === value;
      button.setAttribute("aria-checked", on ? "true" : "false");
      if (button.tabIndex !== undefined) button.tabIndex = on ? 0 : -1;
    });
  }
  function applyTheme(country, style) {
    const root = document.documentElement;
    theme.country = DESIGN_COUNTRIES.indexOf(country) >= 0 ? country : selectedCountry();
    theme.style = DESIGN_STYLES.indexOf(style) >= 0 ? style : rememberedStyle();
    if (root && root.dataset) {
      root.dataset.country = theme.country;
      root.dataset.style = theme.style;
    }
    markGroup(host("councilCountryGroup"), "data-country", theme.country);
    markGroup(host("councilStyleGroup"), "data-style", theme.style);
    const value = host("councilThemeValue");
    if (value) value.textContent = "국가 " + COUNTRY_NAMES[theme.country] + " · 스타일 " + STYLE_NAMES[theme.style];
    rememberStyle(theme.style);
    return { country: theme.country, style: theme.style };
  }
  function chooseCountry(country) {
    const node = host("councilCountry");
    if (node && node.value !== country) {
      node.value = country;
      if (typeof node.dispatchEvent === "function" && typeof Event === "function") {
        node.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    applyTheme(country, theme.style);
  }
  // role=radio means the arrows move the choice, not the caret.
  function bindGroup(group, attr, choose) {
    if (!group || typeof group.querySelectorAll !== "function") return;
    const buttons = Array.from(group.querySelectorAll("[" + attr + "]"));
    buttons.forEach((button, index) => {
      button.addEventListener("click", () => choose(button.getAttribute(attr)));
      button.addEventListener("keydown", (event) => {
        const key = event && event.key;
        if (key !== "ArrowRight" && key !== "ArrowLeft" && key !== "ArrowDown" && key !== "ArrowUp") return;
        if (typeof event.preventDefault === "function") event.preventDefault();
        const step = (key === "ArrowRight" || key === "ArrowDown") ? 1 : -1;
        const next = buttons[(index + step + buttons.length) % buttons.length];
        if (!next) return;
        choose(next.getAttribute(attr));
        if (typeof next.focus === "function") next.focus();
      });
    });
  }
  function setThemePanel(open) {
    const panel = host("councilThemePanel");
    const trigger = host("councilThemeTrigger");
    theme.open = !!open;
    if (panel) panel.hidden = !open;
    if (trigger) trigger.setAttribute("aria-expanded", open ? "true" : "false");
  }
  function wireTheme() {
    if (session.themeBound) return;
    session.themeBound = true;
    applyTheme(selectedCountry(), rememberedStyle());
    bindGroup(host("councilCountryGroup"), "data-country", chooseCountry);
    bindGroup(host("councilStyleGroup"), "data-style", (style) => applyTheme(theme.country, style));
    const select = host("councilCountry");
    if (select && select.addEventListener) {
      select.addEventListener("change", () => applyTheme(selectedCountry(), theme.style));
    }
    const trigger = host("councilThemeTrigger");
    if (trigger) trigger.addEventListener("click", () => setThemePanel(!theme.open));
    const box = host("councilTheme");
    if (box && box.addEventListener) {
      box.addEventListener("click", (event) => { if (event) event.stopPropagation(); });
    }
    document.addEventListener("click", () => { if (theme.open) setThemePanel(false); });
    document.addEventListener("keydown", (event) => {
      if (!event || event.key !== "Escape") return;
      // 정본의 순서: 팝오버가 먼저 닫히고, 그 다음에 작업실이 홈으로 물러난다.
      if (theme.open) { setThemePanel(false); return; }
      if (session.selected) leaveWorkspace();
    });
  }

  // ── 작업실 전환 ────────────────────────────────────────────────────────
  // The 정본 keeps the home and the editor as two screens. Production hosts each editor
  // inside its own card, so the same result is reached by state, not by moving nodes: the
  // hero and the strip step out, the bar returns to the flow, and the open card becomes the
  // paper. Nothing here touches which panel is open — applySelection still owns that.
  function paintWorkspace(tool) {
    const root = document.documentElement;
    const bar = host("councilWorkspaceBar");
    const title = host("councilWorkspaceTitle");
    if (root && root.classList) root.classList[tool ? "add" : "remove"]("council-in-workspace");
    if (bar) bar.hidden = !tool;
    if (title) title.textContent = tool ? (LABELS[tool] || "") : "";
    // focusToolPanel brought the open card to the top, which carried this bar off the
    // screen with it. The bar is in the flow, so the script brings the reader to it.
    if (tool && bar && typeof bar.scrollIntoView === "function") {
      try { bar.scrollIntoView({ block: "start" }); } catch (_) {}
    }
  }
  function leaveWorkspace() {
    applySelection(null, false);
    const first = cardButtons()[0];
    if (first && typeof first.focus === "function") first.focus();
    if (typeof window.scrollTo === "function") { try { window.scrollTo(0, 0); } catch (_) {} }
  }
  function wireHome() {
    const back = host("councilBack");
    if (back) back.addEventListener("click", leaveWorkspace);
    const cta = host("councilHeroCta");
    if (!cta) return;
    cta.addEventListener("click", () => {
      // The primary CTA previews the tools; authentication is requested only on tool entry.
      const heading = host("councilWorksTitle");
      if (heading && typeof heading.scrollIntoView === "function") {
        try { heading.scrollIntoView({ block: "start" }); } catch (_) {}
      }
      const first = cardButtons()[0];
      if (first && typeof first.focus === "function") first.focus();
    });
  }

  async function init() {
    bodies = {
      speech: host("councilSpeechBody"),
      sns: host("councilSnsBody"),
      meeting: host("councilMeetingBody"),
    };
    bindCards();
    bindAuthForm();
    // The design axes belong to the page, not to the session: a signed-out visitor sees
    // the cinematic home and may change country and style before logging in.
    wireTheme();
    wireHome();
    // The page runs init() once at load; a second call must not stack a second
    // set of listeners, or one click would open and immediately close the panel.
    session.bound = true;
    const auth = await checkSignedIn();
    session.signedIn = auth.signedIn;
    offerGoogle(auth.methods);
    if (!session.signedIn) {
      // fail-closed: the tool builders are not attached while signed out. The
      // cards stay readable as descriptions, and choosing one opens the in-page
      // login instead of sending the visitor to Chat.
      // #6127: when the server could not answer at all, say so. The gate stays
      // closed either way; only the report to the user differs, so a runtime
      // fault is not presented as "you are not signed in".
      // Keep the first visit focused on the cinematic home and tool cards.
      // The existing login form opens only after the visitor chooses a tool.
      hideAuthPanel();
      setBadge("");
      session.unavailable = !!auth.unavailable;
      return { signedIn: false, tools: null, selected: null, unavailable: !!auth.unavailable };
    }
    setBadge("로그인됨");
    hideAuthPanel();
    syncCountrySelect();
    // syncCountrySelect sets the value without dispatching, so the pills follow it here.
    applyTheme(selectedCountry(), theme.style);
    buildToolPanels();
    const tool = toolFromUrl() || rememberedTool();
    applySelection(TOOLS.indexOf(tool) >= 0 ? tool : null, false);
    return {
      signedIn: true,
      tools: { speech: speechModule, sns: snsModule, meeting: meetingModule },
      selected: session.selected,
    };
  }

  window.PadiemCouncilApps = {
    init,
    state: () => ({
      signedIn: session.signedIn,
      built: session.built,
      bound: session.bound,
      selected: session.selected,
      pending: session.pending,
    }),
    select: (tool, moveFocus) => applySelection(tool, moveFocus),
    theme: () => ({ country: theme.country, style: theme.style, open: theme.open,
                    countries: DESIGN_COUNTRIES.slice(), styles: DESIGN_STYLES.slice() }),
    setTheme: (country, style) => applyTheme(country, style),
    workspace: () => (session.selected ? "workspace" : "home"),
    openLogin: (tool) => openLoginHere(tool),
    sessionLost: () => markSessionLost(),
    speech: speechModule,
    sns: snsModule,
    meeting: meetingModule,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => { init(); }, { once: true });
  } else {
    init();
  }
})();
