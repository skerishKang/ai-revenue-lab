"use strict";
// #5007 B66 consultation vs general chat, "견적 상담 이어가기" restore, and the
// composer input lock. Source-contract regressions: these assertions fail if the
// defects are restored.
//
// 1. A general question must not be answered with a quote prompt. The server owns
//    `quote.mode`; the browser may only print `next_question` while authoring.
// 2. The resume chip must call the real restore flow, not just move focus.
// 3. An in-flight AI turn must keep the textarea writable; only submit is blocked.
// 4. New quote must keep the server-owned reset so old facts cannot mix in.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const easy = fs.readFileSync(path.join(__dirname, "..", "easy-mode.js"), "utf8");

/* 1. General chat vs quote authoring ------------------------------- */

// The unconditional append is the defect: `next_question` is derived from the
// still-missing quote fields and is present even for ordinary answers.
assert.doesNotMatch(
  easy,
  /if \(result\.quote && result\.quote\.next_question &&/,
  "next_question must not be printed from the quote payload alone"
);
assert.match(
  easy,
  /result\.quote\.mode === "quote_authoring" && result\.quote\.next_question/,
  "next_question is gated on the server-owned quote_authoring mode"
);

/* 2. "견적 상담 이어가기" restores stored state ------------------- */

assert.match(
  easy,
  /async function resumeQuoteConsultation\(\)/,
  "a real consultation restore function must exist"
);
assert.match(
  easy,
  /\{ label: "견적 상담 이어가기", action: resumeQuoteConsultation \}/,
  "the resume chip must call the restore flow"
);
assert.doesNotMatch(
  easy,
  /\{ label: "견적 상담 이어가기", action: \(\) => composer\.focus\(\) \}/,
  "the resume chip must not be a focus-only no-op"
);
// Reuses the existing owner-scoped server state slot; no second store.
assert.match(
  easy,
  /await bridge\.quoteConversation\("state"\)/,
  "restore must reuse the existing authenticated conversation state API"
);
// Resumes from the server's last valid step.
assert.match(
  easy,
  /state\.mode === "quote_authoring" \|\| state\.awaiting_method/,
  "restore must resume an authoring or awaiting-method consultation"
);
// No stored consultation -> a truthful message, not a fake resume.
assert.match(
  easy,
  /이어서 진행할 저장된 견적 상담이 없습니다/,
  "an absent stored consultation must be explained, not faked"
);
// A restore failure must not leave the composer locked.
assert.match(
  easy,
  /저장된 견적 상담을 불러오지 못했습니다\.[\s\S]{0,400}setInput\(submitFreeFormText/,
  "a failed restore must return a usable composer"
);

/* 3. Composer input lock ------------------------------------------- */

assert.match(
  easy,
  /function blockSend\(note\)/,
  "an in-flight turn needs a send-only block, not a text block"
);
assert.match(
  easy,
  /function blockSend\(note\) \{[\s\S]{0,220}composer\.disabled = false;/,
  "blockSend must leave the textarea writable"
);
assert.match(
  easy,
  /function blockSend\(note\) \{[\s\S]{0,260}sendButton\.disabled = true;/,
  "blockSend must block only the duplicate submit"
);

// setInput is the single re-enable point and must clear every lock it owns.
assert.match(
  easy,
  /function setInput\(handler, placeholder\) \{[\s\S]{0,260}composer\.disabled = false;[\s\S]{0,260}composer\.readOnly = false;/,
  "setInput must clear both the disabled and readOnly locks"
);

// The pending AI turns must use blockSend, never disableInput.
assert.match(easy, /blockSend\("AI 요청을 처리하는 중입니다\./);
assert.match(easy, /blockSend\("AI가 답변하는 동안 잠시 기다려 주세요\./);
assert.match(easy, /blockSend\("견적을 만드는 동안에는 전송만 잠시 멈춥니다\./);
assert.doesNotMatch(
  easy,
  /disableInput\("AI 요청을 처리하는 중입니다\."\)/,
  "the AI processing note must not lock the text field"
);
assert.doesNotMatch(
  easy,
  /disableInput\("AI가 답변하는 동안 잠시 기다려 주세요\."\)/,
  "waiting for an answer must not lock the text field"
);

// Genuine read-only list screens keep the existing lock.
assert.match(easy, /function disableInput\(note\)/, "read-only screens keep disableInput");

/* 4. New quote must not inherit the previous consultation ----------- */

assert.match(
  easy,
  /if \(!options \|\| options\.history !== false\) resetServerQuoteConversation\(\);/,
  "a new quote still resets the server-owned conversation"
);
assert.match(
  easy,
  /await pendingQuoteReset;/,
  "the next turn still waits for the server reset instead of reusing old facts"
);

console.log("B66_5007_CONSULTATION_AND_INPUT_CONTRACT=PASS");