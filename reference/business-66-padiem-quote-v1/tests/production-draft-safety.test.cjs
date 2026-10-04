const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const Core = require("../quote-core.js");
const History = require("../quote-history.js");

const production = Core.createProductionDraft();

assert.equal(production.sender.company, "", "Production sender starts blank");
assert.equal(production.sender.presetId, "custom", "Production sender is not the demo preset");
assert.deepEqual(
  production.recipient,
  { company: "", person: "", address: "", email: "" },
  "Production recipient starts blank"
);
assert.deepEqual(
  production.items,
  [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }],
  "Production draft starts with one blank line item"
);
assert.equal(production.memo, "", "Production memo starts blank");
assert.deepEqual(
  Core.printReadiness(production),
  { ready: false, missing: ["sender_company", "recipient", "items"] },
  "Production startup draft is never print-ready"
);
assert.equal(
  History.isMeaningfulDraft(production),
  false,
  "truthful Production startup draft is not shown as resumable work"
);

const legacyDemo = Core.createDefaultDraft();
assert.equal(
  History.isMeaningfulDraft(legacyDemo),
  false,
  "untouched legacy demo state remains non-resumable"
);
assert.equal(
  Core.printReadiness(legacyDemo).ready,
  true,
  "explicit demo fixture remains available for tests/demos only"
);

const appSource = fs.readFileSync(path.join(__dirname, "..", "app.js"), "utf8");
assert.ok(
  appSource.includes("let draft = loadDraft() || Core.createProductionDraft();"),
  "app startup uses Production draft authority"
);
assert.ok(
  appSource.includes('const fresh = Core.createProductionDraft();'),
  "new Production quote allocation starts from blank business facts"
);
assert.ok(
  appSource.includes("isUntouchedLegacyDemoDraft"),
  "app migrates untouched legacy demo startup state"
);
assert.ok(
  !appSource.includes("let draft = loadDraft() || Core.createDefaultDraft();"),
  "app never falls back to printable demo data"
);

const repoRoot = path.join(__dirname, "..", "..", "..");
const workflow = fs.readFileSync(
  path.join(repoRoot, ".github", "workflows", "b66-neutral-pages-beta.yml"),
  "utf8"
);
assert.ok(
  !workflow.includes("grep -F '샘플 공급사'"),
  "deploy smoke no longer depends on demo business text"
);
assert.ok(
  workflow.includes("grep -F 'id=\"easyView\"'"),
  "deploy smoke uses a stable product structure marker"
);

console.log("B66_PRODUCTION_DRAFT_SAFETY=PASS");
console.log("PRODUCTION_DEFAULT_DRAFT_PRINT_READY=NO");
console.log("DEMO_BUSINESS_FACTS_CAN_BECOME_FINAL_QUOTE=0");
console.log("PRODUCTION_DEPLOY_GUARD_REQUIRES_DEMO_BUSINESS_DATA=NO");
