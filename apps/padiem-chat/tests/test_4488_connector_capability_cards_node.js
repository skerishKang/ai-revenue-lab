"use strict";
const assert = require("node:assert/strict");
const { join } = require("node:path");
const STATIC = join(__dirname, "..", "static");
const api = require(join(STATIC, "claw-connector-capability-cards.js"));

const ids = (list) => list.map((c) => c.id);

{
  const cards = api.capabilityCards();
  assert.equal(cards.length, 4, "exactly four capability cards");
  assert.deepEqual(ids(cards), ["computer", "google-drive", "github", "web"]);
}

{
  const toggles = api.toggleCards();
  assert.deepEqual(ids(toggles), ["computer", "google-drive", "github"],
    "only computer/drive/github are toggle cards");
  assert.equal(api.nonToggleCards().length, 1);
  assert.equal(api.nonToggleCards()[0].id, "web", "web card has no toggle");
  assert.equal(api.isToggleCard("web"), false);
  assert.equal(api.isToggleCard("github"), true);
  assert.equal(api.isWebCard("web"), true);
}

{
  const implemented = api.implementedToggleCards();
  assert.deepEqual(ids(implemented), ["google-drive"],
    "only Google Drive has a live auth endpoint; others are preparing");
  const preparing = api.preparingCards();
  assert.deepEqual(ids(preparing), ["computer", "github"],
    "unimplemented APIs are marked preparing, not attempted");
}

{
  assert.equal(api.statusFor("computer", false), "preparing");
  assert.equal(api.statusFor("github", true), "preparing");
  assert.equal(api.statusFor("web", false), "usable");
  assert.equal(api.statusFor("google-drive", false), "disconnected");
  assert.equal(api.statusFor("google-drive", true), "connected");
}

{
  assert.equal(api.shouldAttemptConnect("computer"), false);
  assert.equal(api.shouldAttemptConnect("github"), false);
  assert.equal(api.shouldAttemptConnect("web"), false);
  assert.equal(api.shouldAttemptConnect("google-drive"), true);
}

console.log("connector-capability-cards: all assertions passed");
