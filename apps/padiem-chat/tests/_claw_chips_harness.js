
const payload = JSON.parse(process.env.CLAW_CHIPS_PAYLOAD);
const element = () => ({
  dataset: {}, textContent: "", hidden: false, value: "",
  setAttribute() {}, removeAttribute() {}, addEventListener() {},
  querySelector() { return null; }, querySelectorAll() { return []; },
  click() {}, closest() { return null; }, contains() { return false; },
});
const shell = element(); shell.dataset.state = "claw";
const owner = element(); owner.dataset.accountState = "signed_in";
const workspace = element(); workspace.dataset.view = "general";
const pcCard = element();
const pcStatus = element();
const chipPc = element();
const chipDrive = element();
const chipGithub = element();
const cardDrive = element();
const cardGithub = element();
const statusDrive = element();
const statusGithub = element();
const byQuery = {
  ".app-shell": shell,
  ".sidebar-account": owner,
  '[data-claw-card="computer"]': pcCard,
  '[data-claw-card="drive"]': cardDrive,
  '[data-claw-card="github"]': cardGithub,
  '[data-claw-connection="pc"]': chipPc,
  '[data-claw-connection="drive"]': chipDrive,
  '[data-claw-connection="github"]': chipGithub,
};
const byId = {
  clawWorkspace: workspace,
  clawPcCardStatus: pcStatus,
  clawDriveCardStatus: statusDrive,
  clawGithubCardStatus: statusGithub,
};
global.document = {
  documentElement: {lang: "ko"},
  hidden: false,
  querySelector(sel) { return byQuery[sel] || null; },
  getElementById(id) { return byId[id] || null; },
  addEventListener() {},
};
global.window = {addEventListener() {}, location: {assign() {}}};
global.MutationObserver = class { observe() {} disconnect() {} };
global.fetch = async (url) => {
  if (String(url).includes("/api/claw/local-access/devices")) {
    return {ok: true, status: 200, text: async () => JSON.stringify(payload)};
  }
  return {ok: true, status: 200, text: async () => JSON.stringify({})};
};
const fs = require("node:fs");
eval(fs.readFileSync(process.env.CLAW_CHIPS_MODULE, "utf8"));
(async () => {
  // The reset() state is "unknown"; the real refresh settles it. Wait for a
  // settled phase, not for a non-empty text, because reset() already writes
  // a generic line.
  for (let i = 0; i < 60; i += 1) {
    if (pcCard.dataset.pcPhase && pcCard.dataset.pcPhase !== "unknown") break;
    await new Promise((r) => setTimeout(r, 25));
  }
  await new Promise((r) => setTimeout(r, 50));
  console.log(JSON.stringify({
    text: pcStatus.textContent,
    phase: pcCard.dataset.pcPhase || null,
    chip: chipPc.dataset.connectionState || null,
  }));
})();
