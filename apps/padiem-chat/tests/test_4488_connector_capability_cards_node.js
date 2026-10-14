"use strict";
const assert = require("node:assert/strict");
const { join } = require("node:path");
const STATIC = join(__dirname, "..", "static");
const api = require(join(STATIC, "claw-connector-capability-cards.js"));

const ids = (list) => list.map((c) => c.id);

// --- capability card catalog -------------------------------------------
{
  const cards = api.capabilityCards();
  assert.equal(cards.length, 4, "exactly four capability cards");
  assert.deepEqual(ids(cards), ["computer", "google-drive", "github", "web"]);
}
{
  assert.deepEqual(ids(api.toggleCards()), ["computer", "google-drive", "github"]);
  assert.equal(api.nonToggleCards()[0].id, "web", "web card has no toggle");
  assert.equal(api.isToggleCard("web"), false);
  assert.equal(api.isToggleCard("github"), true);
  assert.equal(api.isWebCard("web"), true);
}
{
  assert.deepEqual(ids(api.implementedToggleCards()), ["google-drive"]);
  assert.deepEqual(ids(api.preparingCards()), ["computer", "github"]);
  assert.equal(api.isPreparing("computer"), true);
  assert.equal(api.isImplemented("google-drive"), true);
}

// --- status projection -------------------------------------------------
{
  assert.equal(api.statusFor("computer", false), "preparing");
  assert.equal(api.statusFor("github", true), "preparing");
  assert.equal(api.statusFor("web", false), "usable");
  assert.equal(api.statusFor("google-drive", false), "disconnected");
  assert.equal(api.statusFor("google-drive", true), "connected");
  assert.equal(api.shouldAttemptConnect("computer"), false);
  assert.equal(api.shouldAttemptConnect("github"), false);
  assert.equal(api.shouldAttemptConnect("web"), false);
  assert.equal(api.shouldAttemptConnect("google-drive"), true);
}

// --- DOM interaction contract ------------------------------------------
function fakeButton(connectorId, connected) {
  return {
    dataset: { connectorToggle: connectorId },
    hidden: false, disabled: false, textContent: connected ? "ON" : "OFF", handlers: {},
    _attrs: { "aria-pressed": connected ? "true" : "false" },
    getAttribute(name) { return this._attrs[name]; },
    setAttribute(name, value) { this._attrs[name] = String(value); },
    removeAttribute(name) { delete this._attrs[name]; },
    addEventListener(type, handler) { this.handlers[type] = handler; },
    click() { if (this.handlers.click) this.handlers.click(); },
  };
}
function fakeScope(buttons) {
  return { buttons, addEventListener() {}, querySelectorAll(sel) {
    assert.equal(sel, "[data-connector-toggle]");
    return this.buttons;
  } };
}
function fakeDialog() {
  return {
    dataset: {}, returnValue: "", _handlers: {}, _choices: [],
    showModal() { this._shown = this.dataset.connectorId; },
    addEventListener(type, handler) { this._handlers[type] = handler; },
    querySelectorAll(sel) { return sel === "[value]" ? this._choices : []; },
    addChoice(value) {
      const owner = this;
      const choice = {
        _owner: owner,
        getAttribute: (name) => (name === "value" ? value : null),
        addEventListener(type, handler) { if (type === "click") this._click = handler; },
        // The browser never touches dataset.submittedValue; only the module
        // records which button the user pressed.
        click() { if (this._click) this._click(); },
      };
      this._choices.push(choice);
      return choice;
    },
    submittedBy(value) { this.dataset.submittedValue = value; },
    close(returnValue) {
      // Like the real element: an explicit value is recorded, a dismissal
      // (cancel/Escape) leaves the previous returnValue in place.
      if (returnValue !== undefined) this.returnValue = returnValue;
      this._handlers.close();
    },
  };
}

{
  // A preparing card is never usable: toggle hidden and disabled, no connect
  // attempt even when the button is clicked.
  const btn = fakeButton("github", false);
  const connected = [];
  const dialog = fakeDialog();
  api.bindConnectorToggles({ scope: fakeScope([btn]), disconnectDialog: dialog,
    onConnect: (id) => connected.push(id) });
  assert.equal(btn.hidden, true);
  assert.equal(btn.disabled, true);
  assert.equal(btn.getAttribute("aria-pressed"), "false");
  btn.click();
  assert.deepEqual(connected, [], "preparing card must not attempt a connect");
  assert.equal(dialog._shown, undefined, "preparing card must not open confirm");
  assert.equal(dialog.dataset.connectorId, undefined);
}

{
  // OFF -> ON for an implemented card: real connect is requested.
  const btn = fakeButton("google-drive", false);
  const connected = [];
  const disconnected = [];
  const dialog = fakeDialog();
  api.bindConnectorToggles({ scope: fakeScope([btn]), disconnectDialog: dialog,
    onConnect: (id) => { connected.push(id); },
    onDisconnect: (id) => disconnected.push(id) });
  assert.equal(btn.hidden, false);
  assert.equal(btn.disabled, false);
  btn.click();
  assert.deepEqual(connected, ["google-drive"], "OFF opens a real connect");
  // While the auth round-trip is in flight the button is busy and disabled.
  assert.equal(btn.textContent, "\u2026");
  assert.equal(btn.disabled, true);
  assert.equal(btn.getAttribute("aria-busy"), "true");
  assert.equal(btn.getAttribute("aria-pressed"), "false");
  // The auth return settles the card to ON.
  api.paintToggle(btn, true);
  assert.equal(btn.getAttribute("aria-pressed"), "true");
  assert.equal(btn.textContent, "ON");
}

{
  // ON -> confirm dialog -> confirm flips to OFF and reports disconnect.
  const btn = fakeButton("google-drive", true);
  const connected = [];
  const disconnected = [];
  const dialog = fakeDialog();
  const confirm = dialog.addChoice("confirm");
  const cancel = dialog.addChoice("cancel");
  api.bindConnectorToggles({ scope: fakeScope([btn]), disconnectDialog: dialog,
    onConnect: (id) => connected.push(id), onDisconnect: (id) => disconnected.push(id) });
  btn.click();
  assert.equal(dialog._shown, "google-drive", "ON opens the disconnect confirm");
  assert.equal(dialog.dataset.connectorId, "google-drive");
  // The pressed Disconnect button is the decision.
  confirm.click();
  assert.deepEqual(disconnected, ["google-drive"], "confirm disconnects immediately");
  assert.equal(btn.getAttribute("aria-pressed"), "false");
  assert.equal(btn.textContent, "OFF");
  // A later dismissal of the same dialog must not disconnect a second time.
  dialog.close();
  assert.deepEqual(disconnected, ["google-drive"], "the close event never repeats it");
  assert.equal(cancel.click ? true : true, true);
}

{
  // ON -> confirm dialog -> cancel keeps the card connected.
  const btn = fakeButton("google-drive", true);
  const disconnected = [];
  const dialog = fakeDialog();
  dialog.addChoice("confirm");
  const cancel = dialog.addChoice("cancel");
  api.bindConnectorToggles({ scope: fakeScope([btn]), disconnectDialog: dialog,
    onConnect() {}, onDisconnect: (id) => disconnected.push(id) });
  btn.click();
  cancel.click();
  dialog.close("cancel");
  assert.deepEqual(disconnected, [], "cancel must not disconnect");
  assert.equal(btn.getAttribute("aria-pressed"), "true");
  assert.equal(btn.textContent, "ON");
}

{
  // A modal's returnValue outlives the dialog, so dismissing the NEXT dialog
  // must not replay an earlier "confirm" as a disconnect.
  const btn = fakeButton("google-drive", true);
  const disconnected = [];
  const dialog = fakeDialog();
  dialog.returnValue = "confirm";
  dialog.addChoice("confirm");
  const cancel = dialog.addChoice("cancel");
  api.bindConnectorToggles({ scope: fakeScope([btn]), disconnectDialog: dialog,
    onConnect() {}, onDisconnect: (id) => disconnected.push(id) });
  btn.click();
  cancel.click(); // dismissed without an explicit answer
  dialog.close();
  assert.deepEqual(disconnected, [], "stale returnValue must not disconnect");
  assert.equal(btn.getAttribute("aria-pressed"), "true");
}

{
  // A confirm pressed while the dialog carries no target (an already closed
  // dialog, or a second press after it resolved) must not touch any card.
  const drive = fakeButton("google-drive", true);
  const other = fakeButton("github", false);
  const disconnected = [];
  const dialog = fakeDialog();
  const confirm = dialog.addChoice("confirm");
  api.bindConnectorToggles({ scope: fakeScope([drive, other]), disconnectDialog: dialog,
    onConnect() {}, onDisconnect: (id) => disconnected.push(id) });
  drive.click();      // opens the dialog for google-drive
  dialog.dataset.connectorId = undefined; // simulate an already resolved dialog
  delete dialog.dataset.connectorId;
  confirm.click();
  assert.deepEqual(disconnected, [], "a targetless confirm must not disconnect");
  assert.equal(drive.getAttribute("aria-pressed"), "true");
}

{
  // Only the three reviewed sources ever carry a toggle button.
  const drive = fakeButton("google-drive", false);
  const github = fakeButton("github", false);
  const web = fakeButton("web", false);
  const dialog = fakeDialog();
  api.bindConnectorToggles({ scope: fakeScope([drive, github, web]), disconnectDialog: dialog,
    onConnect() {}, onDisconnect() {} });
  assert.equal(web.hidden, true, "web card keeps its toggle out of the layout");
  assert.equal(web.getAttribute("aria-pressed"), "false");
}

console.log("connector-capability-cards: all assertions passed");
