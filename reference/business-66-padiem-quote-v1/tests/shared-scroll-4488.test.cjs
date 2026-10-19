"use strict";
const assert = require("node:assert/strict");
const shared = require("../shared-conversation-scroll.js");
assert.equal(shared.VERSION, "shared-scroll-v1");
assert.equal(shared.NEAR_BOTTOM_PX, 120);
/* B66 old contract: a missing container never blocks follow. */
assert.equal(shared.isNearBottom(null), true);
/* Near the newest turn (gap 50 < 120) -> follow. */
const near = { scrollHeight: 1000, scrollTop: 850, clientHeight: 100 };
assert.equal(shared.remainingToEnd(near), 50);
assert.equal(shared.isNearBottom(near), true);
/* Reading back (gap 800 >= 120) -> no auto jump. */
const back = { scrollHeight: 1000, scrollTop: 100, clientHeight: 100 };
assert.equal(shared.remainingToEnd(back), 800);
assert.equal(shared.isNearBottom(back), false);
/* Exact 120 boundary stays exclusive of "near" (old `< 120`). */
const edge = { scrollHeight: 1000, scrollTop: 780, clientHeight: 100 };
assert.equal(shared.remainingToEnd(edge), 120);
assert.equal(shared.isNearBottom(edge), false);
shared.followToBottom(near);
assert.equal(near.scrollTop, 1000);
assert.equal(shared.followToBottom(null), false);
console.log("SHARED_CHAT_CLAW_B66_SCROLL=PASS");
