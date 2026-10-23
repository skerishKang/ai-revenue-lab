(() => {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
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
    const tabs = document.querySelectorAll(".util-tab");
    const panels = {
      speech: document.getElementById("utilSpeechPanel"),
      sns: document.getElementById("utilSnsPanel"),
      meeting: document.getElementById("utilMeetingPanel"),
    };

    let lastPayload = null;

    function showUtil() {
      // hide other views
      document.querySelectorAll(".claw-workspace, .conversation, .library-view").forEach((el) => {
        if (el.id !== "utilView") el.hidden = true;
      });
      utilView.hidden = false;
    }

    function hideUtil() {
      utilView.hidden = true;
    }

    utilNav.addEventListener("click", () => {
      if (utilView.hidden) showUtil();
      else hideUtil();
    });

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        const key = tab.dataset.util;
        Object.keys(panels).forEach((k) => {
          if (panels[k]) panels[k].hidden = k !== key;
        });
      });
    });

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
      if (style) {
        prompt += `\n아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:\n---\n${style}\n---\n`;
      }
      prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
      return prompt;
    }

    async function generate(form) {
      const prompt = buildPrompt(form);
      lastPayload = prompt;
      speechResult.hidden = false;
      speechOutput.value = "생성 중...";
      try {
        const res = await fetch("/api/chat", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: [{ role: "user", content: prompt }],
            mode: "auto",
          }),
        });
        if (!res.ok) {
          speechOutput.value = "생성 실패: " + res.status;
          return;
        }
        const data = await res.json();
        const answer = data && data.answer ? data.answer : (data && data.message ? data.message : JSON.stringify(data));
        speechOutput.value = answer;
      } catch (e) {
        speechOutput.value = "생성 실패: " + (e && e.message ? e.message : e);
      }
    }

    if (speechForm) {
      speechForm.addEventListener("submit", (e) => {
        e.preventDefault();
        generate(speechForm);
      });
    }
    if (regenBtn) {
      regenBtn.addEventListener("click", () => {
        if (speechForm) generate(speechForm);
      });
    }
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(speechOutput.value);
          copyBtn.textContent = "복사됨";
          setTimeout(() => { copyBtn.textContent = "복사"; }, 1500);
        } catch (_) {}
      });
    }
    if (downloadBtn) {
      downloadBtn.addEventListener("click", () => {
        const blob = new Blob([speechOutput.value], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "speech.txt";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      });
    }
  });
})();
