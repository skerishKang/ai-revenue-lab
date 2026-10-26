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

  async function apiChat(prompt, util) {
    // Same rule as util-menu.js apiChat / app.js selectedProductTier().
    // The util scope (PR #5916 contract) is the request's routing label:
    // it keeps a declared utility out of the shared native-calendar branch
    // (including try_native_calendar_chat's own second classification) and
    // the server refuses unknown scopes before any model call. It grants no
    // identity, tier, entitlement or tool scope and is not an auth input.
    const selected = window.PadiemTierSelection?.get?.();
    const tier = ["free", "plus", "pro", "max", "admin"].includes(selected) ? selected : "free";
    const payload = { messages: [{ role: "user", content: prompt }], mode: "auto", tier };
    if (util) payload.util = util;
    const res = await fetch("/api/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
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
      body: JSON.stringify({ name: name, media_type: mediaType || "text/plain", text: text }),
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
        } else {
          alert("저장 실패");
        }
      });
    }

    return { build(host) { buildForm(host); }, buildPrompt: buildSpeechPrompt };
  })();

  // ── sns module (prompt template ported verbatim from util-menu.js) ───────
  // Text composition only in this base app. The stored-photo composition
  // contract (#5728, LOCAL 1, already merged to main via PR #5924) is
  // deliberately NOT copied here; connecting it through an adapter is
  // separate follow-up work — see the README boundary note.

  function buildSnsPrompt(form, platform) {
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
        });
        tabDiv.appendChild(b);
      });
      form.appendChild(tabDiv);

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
      const actions = el("div", "council-actions");
      const copyB = el("button", null, "복사");
      copyB.type = "button";
      copyB.id = "councilSnsCopy";
      const dlB = el("button", null, "TXT 다운로드");
      dlB.type = "button";
      dlB.id = "councilSnsDownload";
      actions.append(copyB, dlB);
      result.append(title, output, actions);

      host.replaceChildren(form, result);

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(buildSnsPrompt(form, platform), "sns"); }
        catch (err) { output.value = "생성 실패: " + (err && err.message ? err.message : err); }
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
        const name = "sns-" + platform + ".txt";
        const file = await saveProjectFile(pid, name, text);
        if (file) {
          saveBtn.textContent = "저장됨";
          setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
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
        const meetingFiles = files.filter((f) => (f.name || "").endsWith(".txt"));
        arc.replaceChildren();
        arc.appendChild(el("h3", null, "활동 기록"));
        if (!meetingFiles.length) {
          arc.appendChild(el("p", "council-empty", "저장된 회의 기록이 없습니다."));
          return;
        }
        const bookBtn = el("button", "council-generate", "선택 기록으로 책/활동집 초안 생성");
        bookBtn.type = "button";
        bookBtn.id = "councilBookGenerate";
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
          li.appendChild(cb);
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
        bookActions.append(bookCopy, bookDl);
        bookResult.appendChild(bookActions);
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
      }

      return { refreshArchive };
    }

    return {
      build(host) { buildForm(host); },
      buildPrompt: buildMeetingPrompt,
      buildBookPrompt,
    };
  })();

  // ── independent entry wiring: auth gate, then build all three tools ──────

  async function checkSignedIn() {
    try {
      const res = await fetch("/api/auth/status", { credentials: "include" });
      if (!res.ok) return false;
      const data = await res.json().catch(() => null);
      return !!(data && data.authenticated === true);
    } catch (_) {
      return false;
    }
  }

  async function init() {
    const bodies = {
      speech: document.getElementById("councilSpeechBody"),
      sns: document.getElementById("councilSnsBody"),
      meeting: document.getElementById("councilMeetingBody"),
    };
    const signedIn = await checkSignedIn();
    const badge = document.getElementById("councilAuthBadge");
    const note = document.getElementById("councilSigninNote");
    if (!signedIn) {
      if (badge) badge.textContent = "로그인 필요";
      if (note) note.hidden = false;
      // fail-closed: the tool builders are not attached while signed out.
      return { signedIn, tools: null };
    }
    if (badge) badge.textContent = "로그인됨";
    const tools = {
      speech: speechModule,
      sns: snsModule,
      meeting: meetingModule,
    };
    Object.keys(bodies).forEach((key) => {
      const host = bodies[key];
      if (host && tools[key]) tools[key].build(host);
    });
    return { signedIn, tools };
  }

  window.PadiemCouncilApps = {
    init,
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
