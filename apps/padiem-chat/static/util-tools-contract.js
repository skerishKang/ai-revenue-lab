/*
 * #7173 PR2 · The generation contract for the three Util tools.
 *
 * File boundary: prompt shapes, the same-origin stream call and the failure
 * copy live here; util-tools.js owns the screens. Both are Util-app files —
 * Chat app.js gains nothing (R5 #7216).
 *
 * The contract is the SHIPPED council/Chat one (apps/padiem-council-apps/
 * static/council-app.js after #6562), restated here without a second backend:
 *   POST /api/chat/stream {messages:[{role:"user",content}], tier,
 *   util:"speech"|"sns"|"meeting"} — same origin, same session cookie, the
 *   same signed-in-only rule, the same tier check and the same usage gate.
 *   The util scope is a routing label only; it grants no identity.
 */
(() => {
  "use strict";

  const LENGTH_MAP = Object.freeze({
    short: "짧게(300자 내외)", medium: "보통(600자 내외)", long: "길게(1000자 내외)",
  });
  const TONE_MAP = Object.freeze({
    formal: "공식적이고 격식 있는", warm: "따뜻하고 친근한", concise: "간결하고 명료한",
  });
  const SNS_TONE_MAP = Object.freeze({
    casual: "캐주얼하고 친근한", professional: "전문적이고 신뢰감 있는", emotional: "감성적이고 따뜻한",
  });
  const PLATFORM_GUIDE = Object.freeze({
    blog: "블로그 게시글: 800-1200자, 제목 포함, 소제목 구분, 상세한 설명",
    facebook: "페이스북 게시글: 300-500자, 친근한 톤, 이모지 적절히, 해시태그 3-5개",
    instagram: "인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부",
  });
  const PLATFORM_TITLE = Object.freeze({ blog: "블로그", facebook: "페이스북", instagram: "인스타그램" });
  const GEN_TIMEOUT_MS = 120000;

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function emptyCopy() {
    return lang() === "en" ? "The answer came back empty. Please try again." : "답변이 비어 왔습니다. 다시 시도해 주세요.";
  }

  // Chat copy table (#5002). The key's own sentence wins; the fallback keeps a
  // missing key from printing a token on screen.
  function localeText(key, fallback) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) { /* the table is optional for a standalone mount */ }
    return fallback;
  }

  // ── prompt builders (ported verbatim from the council app) ───────────────

  function buildSpeechPrompt(values) {
    const v = values || {};
    let prompt = "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.\n\n";
    prompt += `행사명: ${v.event || ""}\n`;
    if (v.date) prompt += `행사 날짜: ${v.date}\n`;
    if (v.place) prompt += `장소: ${v.place}\n`;
    if (v.nature) prompt += `행사 성격: ${v.nature}\n`;
    if (v.audience) prompt += `참석 대상: ${v.audience}\n`;
    if (v.author) prompt += `작성자/직책: ${v.author}\n`;
    if (v.message) prompt += `주요 메시지: ${v.message}\n`;
    if (v.emphasis) prompt += `강조 내용: ${v.emphasis}\n`;
    prompt += `분량: ${LENGTH_MAP[v.length] || "보통"}\n`;
    prompt += `말투: ${TONE_MAP[v.tone] || "공식적"}\n`;
    if (v.style) {
      prompt += `\n아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:\n---\n${v.style}\n---\n`;
    }
    prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
    return prompt;
  }

  function buildSnsPrompt(values, platform) {
    const v = values || {};
    const guide = PLATFORM_GUIDE[platform] || PLATFORM_GUIDE.blog;
    let prompt = `다음 행사 정보를 바탕으로 ${guide}을 작성해 주세요.\n\n`;
    prompt += `행사명: ${v.event || ""}\n`;
    if (v.whenwhere) prompt += `날짜·장소: ${v.whenwhere}\n`;
    prompt += `주요 내용: ${v.content || ""}\n`;
    if (v.memo) prompt += `메모: ${v.memo}\n`;
    if (v.audience) prompt += `대상 독자: ${v.audience}\n`;
    prompt += `문체: ${SNS_TONE_MAP[v.tone] || "전문적이고 신뢰감 있는"}\n`;
    prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
    return prompt;
  }

  function buildMeetingPrompt(values) {
    const v = values || {};
    let prompt = "다음 회의 내용을 정리해 주세요.\n\n";
    prompt += `회의명: ${v.title || ""}\n`;
    if (v.when) prompt += `회의 일시: ${v.when}\n`;
    if (v.attendees) prompt += `참석자: ${v.attendees}\n`;
    prompt += `회의 내용:\n${v.content || ""}\n\n`;
    prompt += "다음 항목으로 정리해 주세요:\n1. 회의 요약 (3-5문장)\n2. 주요 논의사항 (bullet)\n3. 결정사항 (bullet)\n4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n5. 미해결 사항";
    return prompt;
  }

  const PROMPTS = Object.freeze({
    speech: buildSpeechPrompt,
    sns: buildSnsPrompt,
    meeting: buildMeetingPrompt,
  });

  // ── the stream reader ────────────────────────────────────────────────────

  function streamError(data) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const error = new Error("generation failed");
    error.code = code;
    if (code === "empty_upstream_answer") error.empty = true;
    return error;
  }

  function parseSseBlock(block) {
    let event = "message";
    const dataLines = [];
    String(block).replace(/\r\n/g, "\n").split("\n").forEach((line) => {
      if (!line || line.charAt(0) === ":") return;
      const separator = line.indexOf(":");
      const field = separator >= 0 ? line.slice(0, separator) : line;
      let value = separator >= 0 ? line.slice(separator + 1) : "";
      if (value.charAt(0) === " ") value = value.slice(1);
      if (field === "event") event = value;
      if (field === "data") dataLines.push(value);
    });
    if (!dataLines.length) return null;
    return { event: event, data: dataLines.join("\n") };
  }

  // A partial stream is never presented as a complete draft: a frame that says
  // error, an unfinished stream and an empty answer all fail the generation.
  async function readAnswer(res, onDelta) {
    const type = String(res.headers && res.headers.get ? res.headers.get("content-type") : "").toLowerCase();
    const ndjson = /application\/(?:x-)?ndjson/.test(type);
    const streaming = ndjson || /text\/event-stream/.test(type);
    if (!streaming || !res.body || typeof res.body.getReader !== "function") {
      const data = await res.json().catch(() => null);
      if (!data || typeof data.answer !== "string" || !data.answer.trim()) {
        const error = new Error("empty"); error.empty = true; throw error;
      }
      return data.answer;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let answer = "";
    let done = false;
    function consume(text) {
      if (!text.trim()) return;
      const frame = ndjson ? { event: "message", data: text.trim() } : parseSseBlock(text);
      if (!frame) return;
      let data = null;
      try { data = JSON.parse(frame.data); } catch (_) { data = null; }
      if (frame.event === "error" || (data && data.error)) throw streamError(data);
      if (data && typeof data.delta === "string") {
        answer += data.delta;
        if (onDelta) onDelta(answer);
      }
      if (frame.event === "done" || (data && data.done === true)) done = true;
    }
    try {
      while (!done) {
        const item = await reader.read();
        if (item.done) break;
        buffer += decoder.decode(item.value, { stream: true });
        const boundary = ndjson ? /\r?\n/ : /\r?\n\r?\n/;
        let match = boundary.exec(buffer);
        while (match) {
          const text = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          consume(text);
          if (done) break;
          match = boundary.exec(buffer);
        }
      }
      buffer += decoder.decode();
      if (!done && buffer.trim()) consume(buffer);
    } finally {
      try { await reader.cancel(); } catch (_) { /* no-op */ }
    }
    if (!answer.trim()) { const error = new Error("empty"); error.empty = true; throw error; }
    return answer;
  }

  function selectedTier() {
    try {
      if (window.PadiemTierSelection && typeof window.PadiemTierSelection.get === "function") {
        const tier = String(window.PadiemTierSelection.get() || "").toLowerCase();
        if (tier) return tier;
      }
    } catch (_) { /* the selection is presentation state only */ }
    return "free";
  }

  async function apiChat(prompt, util, onDelta) {
    const payload = { messages: [{ role: "user", content: prompt }], tier: selectedTier(), util: util };
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), GEN_TIMEOUT_MS) : null;
    let res;
    try {
      try {
        res = await window.fetch("/api/chat/stream", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
          body: JSON.stringify(payload),
          ...(controller ? { signal: controller.signal } : {}),
        });
      } catch (_) {
        const error = new Error("offline");
        if (controller && controller.signal && controller.signal.aborted) error.timeout = true;
        else error.offline = true;
        throw error;
      }
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const error = new Error("generation failed");
        error.status = res.status;
        error.code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
        if (error.code === "empty_upstream_answer") error.empty = true;
        throw error;
      }
      return await readAnswer(res, onDelta);
    } finally {
      if (timer !== null) clearTimeout(timer);
    }
  }

  function errorMessage(err) {
    if (err && err.empty) return emptyCopy();
    if (err && err.timeout) return localeText("timeout", "응답 시간 초과");
    if (err && err.offline) return localeText("connection-error", "연결 오류");
    const status = err && err.status;
    if (status === 401 || status === 403) {
      return localeText("claw-error-auth-needed", "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.");
    }
    if (status === 429) return localeText("claw-error-rate-limited", "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.");
    return localeText("claw-error-generic", "실행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.");
  }

  window.PadiemUtilContract = Object.freeze({
    PROMPTS: PROMPTS,
    PLATFORM_TITLE: PLATFORM_TITLE,
    apiChat: apiChat,
    errorMessage: errorMessage,
  });
})();
