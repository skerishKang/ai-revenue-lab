"use strict";
// #5007-2 B66 processing-note sync + three-dot answer-ready animation.
//
// 1. The composer caption mirrors the real request lifecycle: it must return
//    to idle on first content/completion, failure, cancel and view switch, and
//    must never outlive its request.
// 2. Chat's three-dot animation is ported into the B66 design; pending turns
//    show dots, and the dots leave with the pending message.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const srcDir = path.join(__dirname, "..");
const easy = fs.readFileSync(path.join(srcDir, "easy-mode.js"), "utf8");
const styles = fs.readFileSync(path.join(srcDir, "styles.css"), "utf8");

/* 1. Caption lifecycle ---------------------------------------------- */

// A single helper owns the idle transition.
assert.match(
  easy,
  /function clearProcessingNote\(\) \{[\s\S]{0,160}\$\("easyComposerNote"\)\.textContent = "";/,
  "clearProcessingNote must exist and reset the caption"
);

// View transitions retire the previous turn's caption.
assert.match(
  easy,
  /function startConversation\(\) \{[\s\S]{0,420}clearProcessingNote\(\);/,
  "startConversation must clear the caption"
);
assert.match(
  easy,
  /function clearConversation\(\) \{[\s\S]{0,320}clearProcessingNote\(\);/,
  "clearConversation must clear the caption"
);

// General chat: failure and transport-error paths must clear the caption.
assert.match(
  easy,
  /setInput\(submitFreeFormText, "다시 질문해 주세요"\);\s*clearProcessingNote\(\);/g,
  "model chat failure paths must clear the caption"
);

// Quote turn: every terminal path (answer, failure, cancel) ends in the same
// finally, so the caption returns to idle once per turn.
assert.match(
  easy,
  /pending\.remove\(\);\s*if \(current\(\)\) \{[\s\S]{0,600}clearProcessingNote\(\);/,
  "the quote turn finally must clear the caption"
);

// Consultation restore errors must clear the caption, not keep the loader text.
assert.match(
  easy,
  /setInput\(submitFreeFormText, "견적 내용을 입력하거나 아래 작업을 선택해 주세요"\);\s*clearProcessingNote\(\);/,
  "restore failures and restores that cannot replay must clear the caption"
);

// The successful general answer keeps its saved/unsaved caption, not idle:
// it must not have been blanket-cleared.
assert.match(
  easy,
  /\? ""\s*:\s*"이 답변은 저장되지 않았습니다/,
  "the unsaved-answer caption must survive completion"
);

/* 2. Three-dot animation --------------------------------------------- */

// Chat's `.typing` is ported as `.easy-typing` in the B66 design.
assert.match(styles, /\.easy-typing \{/, "B66 design must define .easy-typing");
assert.match(styles, /@keyframes easy-pulse/, "B66 design must define the pulse keyframes");
assert.match(
  styles,
  /\.easy-typing i:nth-child\(3\) \{ animation-delay: \.28s; \}/,
  "the third dot must be phase-shifted like Chat"
);

// The dots node mirrors Chat's structure and accessible label.
assert.match(
  easy,
  /dots\.className = "easy-typing";/,
  "pending dots must use the B66 typing class"
);
assert.match(
  easy,
  /dots\.setAttribute\("aria-label", "답변을 준비하고 있습니다"\);/,
  "pending dots must expose an accessible label"
);
assert.match(
  easy,
  /dots\.append\(document\.createElement\("i"\), document\.createElement\("i"\), document\.createElement\("i"\)\);/,
  "pending dots must be three dots"
);

// All AI/restore pending messages use the dots helper, not bare ellipsis text.
assert.doesNotMatch(
  easy,
  /addMessage\("assistant", "(AI가 답변을 작성하고 있습니다|요청을 처리하고 있습니다|저장된 견적 상담을 확인하고 있습니다)[^"]*"\)/,
  "pending turns must not use bare text with an ellipsis"
);
for (const call of [
  "addPendingAssistant()",
]) {
  assert.ok(easy.includes("const pending = " + call), "pending must be built by " + call);
}

// Dots leave with the pending message: every addPendingAssistant result must
// have a matching pending.remove() in the same function scope text.
const pendingCount = (easy.match(/const pending = addPendingAssistant\(\)/g) || []).length;
const removeCount = (easy.match(/pending\.remove\(\)/g) || []).length;
assert.ok(pendingCount >= 3, "all AI turn pendings must use the helper, found " + pendingCount);
assert.ok(removeCount >= pendingCount, "every pending must be removed, found " + removeCount);

// Restore paths use send-only blocking, consistent with #5007-1.
assert.doesNotMatch(
  easy,
  /disableInput\("이전 대화를 불러오/,
  "restore loading/failure must not hard-lock the text field"
);

console.log("B66_5007_PROCESSING_NOTE_AND_TYPING_CONTRACT=PASS");