(() => {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  async function apiChat(prompt) {
    const res = await fetch("/api/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: [{ role: "user", content: prompt }], mode: "auto" }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
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
      body: JSON.stringify({ name: "유틸 작업" }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.project ? data.project.id : null;
  }

  async function saveProjectFile(pid, name, text) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, media_type: "text/plain", text: text }),
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

  ready(() => {
    const utilNav = document.getElementById("utilNavButton");
    const utilView = document.getElementById("utilView");
    if (!utilNav || !utilView) return;

    const speechForm = document.getElementById("utilSpeechForm");
    const speechResult = document.getElementById("utilSpeechResult");
    const speechOutput = document.getElementById("utilSpeechOutput");
    const copyBtn = document.getElementById("utilSpeechCopy");
    const regenBtn = document.getElementById("utilSpeechRegenerate");
    const downloadBtn = document.getElementById("utilSpeechDownload");
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.id = "utilSpeechSave";
    saveBtn.textContent = "저장";
    if (speechResult) {
      const actions = speechResult.querySelector(".util-actions");
      if (actions) actions.appendChild(saveBtn);
    }
    const tabs = document.querySelectorAll(".util-tab");
    const panels = {
      speech: document.getElementById("utilSpeechPanel"),
      sns: document.getElementById("utilSnsPanel"),
      meeting: document.getElementById("utilMeetingPanel"),
    };

    let lastPayload = null;
    let currentPid = null;

    function showUtil() {
      document.querySelectorAll(".claw-workspace, .conversation").forEach((e) => {
        if (e.id !== "utilView") e.hidden = true;
      });
      utilView.hidden = false;
    }
    function hideUtil() { utilView.hidden = true; }
    utilNav.addEventListener("click", () => {
      if (utilView.hidden) showUtil(); else hideUtil();
    });
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        const key = tab.dataset.util;
        Object.keys(panels).forEach((k) => { if (panels[k]) panels[k].hidden = k !== key; });
        if (key === "sns" && !panels.sns.dataset.loaded) buildSns();
        if (key === "meeting" && !panels.meeting.dataset.loaded) buildMeeting();
      });
    });

    // Speech
    function buildPrompt(form) {
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

    async function generateSpeech(form) {
      const prompt = buildPrompt(form);
      lastPayload = prompt;
      speechResult.hidden = false;
      speechOutput.value = "생성 중...";
      try {
        speechOutput.value = await apiChat(prompt);
      } catch (e) {
        speechOutput.value = "생성 실패: " + (e && e.message ? e.message : e);
      }
    }
    if (speechForm) {
      speechForm.addEventListener("submit", (e) => { e.preventDefault(); generateSpeech(speechForm); });
    }
    if (regenBtn) regenBtn.addEventListener("click", () => { if (speechForm) generateSpeech(speechForm); });
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(speechOutput.value); copyBtn.textContent = "복사됨"; setTimeout(() => { copyBtn.textContent = "복사"; }, 1500); } catch (_) {}
    });
    if (downloadBtn) downloadBtn.addEventListener("click", () => { downloadText(speechOutput.value, "speech.txt"); });

    saveBtn.addEventListener("click", async () => {
      const text = speechOutput.value.trim();
      if (!text) return;
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
      const name = (document.querySelector("#utilSpeechForm [name=event]")?.value || "축사").trim() + ".txt";
      const file = await saveProjectFile(currentPid, name, text);
      if (file) {
        saveBtn.textContent = "저장됨";
        setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
        await refreshSpeechList();
      } else {
        alert("저장 실패");
      }
    });

    const savedList = document.createElement("div");
    savedList.id = "utilSpeechSaved";
    savedList.className = "util-saved-list";
    if (speechResult) speechResult.appendChild(savedList);

    async function refreshSpeechList() {
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) return;
      const files = await listProjectFiles(currentPid);
      const speechFiles = files.filter((f) => (f.name || "").endsWith(".txt"));
      savedList.replaceChildren();
      if (!speechFiles.length) {
        const p = el("p", "util-empty", "저장된 축사가 없습니다.");
        savedList.appendChild(p);
        return;
      }
      const ul = document.createElement("ul");
      speechFiles.forEach((f) => {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
        btn.addEventListener("click", async () => {
          const res = await fetch("/api/projects/" + currentPid + "/files/" + f.id, { credentials: "include" });
          if (res.ok) {
            const data = await res.json();
            speechOutput.value = (data && data.file && data.file.name) ? "[저장된 파일: " + data.file.name + "]" : "[저장된 파일]";
            speechResult.hidden = false;
          }
        });
        li.appendChild(btn);
        ul.appendChild(li);
      });
      savedList.appendChild(ul);
    }

    // SNS builder
    function buildSns() {
      const panel = panels.sns;
      if (!panel || panel.dataset.loaded) return;
      panel.dataset.loaded = "1";
      const form = el("form", "util-form");
      form.id = "utilSnsForm";
      // fields
      const fields = [
        ["event", "행사명", "text", true],
        ["whenwhere", "날짜·장소", "text", false],
        ["content", "주요 내용", "textarea", true],
        ["photo", "사진 URL", "text", false],
        ["memo", "메모", "textarea", false],
        ["audience", "대상 독자", "text", false],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 3 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = "text";
          if (req) inp.required = true;
          if (name === "photo") inp.placeholder = "photo URL";
          l.appendChild(inp);
        }
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

      const tabDiv = el("div", "util-sns-tabs");
      const tabNames = { blog: "블로그", facebook: "페이스북", instagram: "인스타그램" };
      let platform = "blog";
      Object.keys(tabNames).forEach((key) => {
        const b = el("button", "util-sns-tab" + (key === "blog" ? " active" : ""), tabNames[key]);
        b.type = "button";
        b.dataset.platform = key;
        b.addEventListener("click", () => {
          tabDiv.querySelectorAll(".util-sns-tab").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          platform = key;
          title.textContent = tabNames[key] + " 게시글";
        });
        tabDiv.appendChild(b);
      });
      form.appendChild(tabDiv);

      const submitBtn = el("button", "util-generate", "생성");
      submitBtn.type = "submit";
      form.appendChild(submitBtn);

      const result = el("div", "util-result");
      result.id = "utilSnsResult";
      result.hidden = true;
      const h3 = el("h3", null, "블로그 게시글");
      h3.id = "utilSnsTitle";
      const output = document.createElement("textarea");
      output.id = "utilSnsOutput";
      output.rows = 12;
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilSnsCopy";
      const regenB = el("button", null, "다시 생성"); regenB.type = "button"; regenB.id = "utilSnsRegen";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilSnsDownload";
      actions.append(copyB, regenB, dlB);
      result.append(h3, output, actions);

      panel.replaceChildren(form, result);
      const title = h3;

      async function gen() {
        const d = new FormData(form);
        const event = (d.get("event") || "").trim();
        const whenwhere = (d.get("whenwhere") || "").trim();
        const content = (d.get("content") || "").trim();
        const photo = (d.get("photo") || "").trim();
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
        if (photo) prompt += `사진 URL: ${photo}\n`;
        if (memo) prompt += `메모: ${memo}\n`;
        if (audience) prompt += `대상 독자: ${audience}\n`;
        prompt += `문체: ${toneMap[tone]}\n`;
        prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt); }
        catch (e) { output.value = "생성 실패: " + (e && e.message ? e.message : e); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      regenB.addEventListener("click", gen);
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "sns-" + platform + ".txt"); });
    }

    // Meeting builder
    function buildMeeting() {
      const panel = panels.meeting;
      if (!panel || panel.dataset.loaded) return;
      panel.dataset.loaded = "1";
      const form = el("form", "util-form");
      form.id = "utilMeetingForm";
      const fields = [
        ["title", "회의명", "text", true],
        ["when", "회의 일시", "datetime-local", false],
        ["attendees", "참석자", "text", false],
        ["content", "회의 내용", "textarea", true],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 6 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = type;
          if (req) inp.required = true;
          l.appendChild(inp);
        }
        form.appendChild(l);
      });
      const submitBtn = el("button", "util-generate", "요약 생성");
      submitBtn.type = "submit";
      form.appendChild(submitBtn);

      const result = el("div", "util-result");
      result.id = "utilMeetingResult";
      result.hidden = true;
      const h3 = el("h3", null, "회의 요약");
      const output = document.createElement("textarea");
      output.id = "utilMeetingOutput";
      output.rows = 12;
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilMeetingCopy";
      const saveB = el("button", null, "저장"); saveB.type = "button"; saveB.id = "utilMeetingSave";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilMeetingDownload";
      actions.append(copyB, saveB, dlB);
      result.append(h3, output, actions);

      const archive = el("div", "util-archive");
      archive.id = "utilMeetingArchive";
      const archiveH = el("h3", null, "활동 기록");
      const archiveEmpty = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
      archive.append(archiveH, archiveEmpty);

      panel.replaceChildren(form, result, archive);

      async function gen() {
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
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt); }
        catch (e) { output.value = "생성 실패: " + (e && e.message ? e.message : e); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      saveB.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (form.querySelector("[name=title]")?.value || "회의").trim() + ".txt";
        const file = await saveProjectFile(currentPid, name, text);
        if (file) {
          saveB.textContent = "저장됨";
          setTimeout(() => { saveB.textContent = "저장"; }, 1500);
          await refreshArchive(archive);
        } else {
          alert("저장 실패");
        }
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "meeting.txt"); });

      async function refreshArchive(arc) {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) return;
        const files = await listProjectFiles(currentPid);
        const meetingFiles = files.filter((f) => (f.name || "").endsWith(".txt"));
        arc.replaceChildren();
        const h = el("h3", null, "활동 기록");
        arc.appendChild(h);
        if (!meetingFiles.length) {
          const p = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
          arc.appendChild(p);
          return;
        }
        const ul = document.createElement("ul");
        meetingFiles.forEach((f) => {
          const li = document.createElement("li");
          const btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
          btn.addEventListener("click", async () => {
            const res = await fetch("/api/projects/" + currentPid + "/files/" + f.id, { credentials: "include" });
            if (res.ok) {
              const data = await res.json();
              const out = document.getElementById("utilMeetingOutput");
              if (out) out.value = "[저장된 파일: " + f.name + "]";
            }
          });
          li.appendChild(btn);
          ul.appendChild(li);
        });
        arc.appendChild(ul);
      }
      refreshArchive(archive);
    }
  });
})();
