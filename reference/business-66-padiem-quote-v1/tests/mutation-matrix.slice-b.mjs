/* MUTATION ACCEPTANCE HARNESS for #3405 Slice B — NOT part of CI.
 *
 * Purpose: prove that the behavioral contracts of the signed-in server quote-history
 * surface are guarded by real behavior tests rather than by markers or string greps.
 * It copies the reference app into a scratch tree, applies one defect at a time to the
 * REAL product source, and runs the CI test list. Every defect must turn the suite RED.
 *
 * This script intentionally breaks product source inside a throwaway copy. It never
 * touches the checkout it was started from. Do not wire it into the deploy workflow:
 * it runs the suite ~10 times and only CENTRAL/LOCAL review needs it.
 *
 *   node tests/mutation-matrix.slice-b.mjs
 *
 * Expected tail:
 *   PREVIOUS_FALSE_GREEN_MUTATIONS=10
 *   POST_CORRECTION_MUTATION_SURVIVORS=0
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(HERE, "..");
const REPO_ROOT = path.join(APP_DIR, "..", "..");
const WORKFLOW = path.join(REPO_ROOT, ".github", "workflows", "b66-neutral-pages-beta.yml");
const SCRATCH = path.join(os.tmpdir(), "b66-slice-b-mutation-matrix");

const workflow = fs.readFileSync(WORKFLOW, "utf8");
const TESTS = [];
workflow.replace(/node tests\/([\w.\-]+\.(?:cjs|mjs))/g, (_m, name) => { TESTS.push(name); return ""; });

function resetTree() {
  if (fs.existsSync(SCRATCH)) fs.rmSync(SCRATCH, { recursive: true, force: true });
  fs.mkdirSync(path.join(SCRATCH, ".github", "workflows"), { recursive: true });
  fs.cpSync(path.join(REPO_ROOT, "reference"), path.join(SCRATCH, "reference"), { recursive: true });
  fs.copyFileSync(WORKFLOW, path.join(SCRATCH, ".github", "workflows", "b66-neutral-pages-beta.yml"));
}

const read = (rel) => fs.readFileSync(path.join(SCRATCH, "reference", path.basename(APP_DIR), rel), "utf8");
const write = (rel, text) => fs.writeFileSync(path.join(SCRATCH, "reference", path.basename(APP_DIR), rel), text);

function patch(rel, from, to) {
  const before = read(rel);
  if (!before.includes(from)) throw new Error("patch target not found in " + rel + ": " + from.slice(0, 60));
  write(rel, before.split(from).join(to));
}

function patchRegex(rel, regex, to) {
  const before = read(rel);
  if (!regex.test(before)) throw new Error("patch regex not found in " + rel + ": " + regex);
  write(rel, before.replace(regex, to));
}

function runSuite() {
  const killers = [];
  for (const name of TESTS) {
    const run = spawnSync(process.execPath, ["tests/" + name], {
      cwd: path.join(SCRATCH, "reference", path.basename(APP_DIR)),
      encoding: "utf8",
      shell: false
    });
    if (run.status !== 0) killers.push(name);
  }
  return killers;
}

/* Every entry is a contract violation a real regression could introduce. */
const MUTATIONS = [
  ["M1 the server-row delete loses its confirmation", () => {
    patchRegex("easy-mode.js",
      /^\s*if \(!window\.confirm\("[^"]*"\)\) return;\r?\n(?=\s*const deletion = App && typeof App\.deleteRecentQuote)/m,
      "");
  }],
  ["M2 copy-as-new returns the historical draft unchanged", () => {
    patchRegex("app.js",
      /function copyHistoryAsNew\(entry, now\) \{[\s\S]*?\n  \}/,
      "function copyHistoryAsNew(entry, now) {\n    if (!entry) return null;\n    return entry.draft;\n  }");
  }],
  ["M3 a resolved server error is replaced by the local envelope", () => {
    patchRegex("easy-mode.js",
      /return App\.listRecentQuotes\(\)\.catch\(\(\) => \(\s*\{ ok: false, authority: "server", error: "history_read_failed" \}\s*\)\);/,
      'return App.listRecentQuotes().then((result) => (result && result.ok === true\n' +
      "      ? result\n" +
      "      : { ok: true, authority: \"local\", envelope: readHistory() }))\n" +
      "      .catch(() => ({ ok: false, authority: \"server\", error: \"history_read_failed\" }));");
  }],
  ["M3b the rejected-read arm substitutes the local envelope", () => {
    patchRegex("easy-mode.js",
      /return App\.listRecentQuotes\(\)\.catch\(\(\) => \(\s*\{ ok: false, authority: "server", error: "history_read_failed" \}\s*\)\);/,
      'return App.listRecentQuotes().catch(() => ({ ok: true, authority: "local", envelope: readHistory() }));');
  }],
  ["M4 app.js removes the local row before the server confirms", () => {
    patch("app.js",
      "    const result = await ServerHistory.deleteQuote(quoteHistoryId);",
      "    const optimisticEnvelope = History.deleteEntry(loadHistoryEnvelope(), quoteHistoryId);\n" +
      "    writePrivateItem(History.HISTORY_STORAGE_KEY, JSON.stringify(optimisticEnvelope));\n" +
      "    const result = await ServerHistory.deleteQuote(quoteHistoryId);");
    patch("app.js",
      "    const envelope = History.deleteEntry(loadHistoryEnvelope(), quoteHistoryId);\n" +
      "    writePrivateItem(History.HISTORY_STORAGE_KEY, JSON.stringify(envelope));",
      "    const envelope = optimisticEnvelope;");
  }],
  ["M5 the UI refetches the list before the DELETE response", () => {
    patch("easy-mode.js",
      '    const deletion = App && typeof App.deleteRecentQuote === "function"',
      '    refreshRecentHistory();\n    const deletion = App && typeof App.deleteRecentQuote === "function"');
    patchRegex("easy-mode.js",
      /^\s*if \(!window\.confirm\("[^"]*"\)\) return;\r?\n(?=\s*refreshRecentHistory\(\);)/m,
      "");
  }],
  ["M6 a stale server envelope survives the account change", () => {
    patch("app.js", "  let serverQuoteNoCandidates = [];",
      "  let serverQuoteNoCandidates = [];\n  let staleServerEnvelope = null;");
    patchRegex("app.js",
      /    const result = await ServerHistory\.listQuotes\(\);\r?\n    if \(!result\.ok\) \{/,
      '    if (staleServerEnvelope) return { ok: true, authority: "server", envelope: staleServerEnvelope, requested: 0 };\n' +
      "    const result = await ServerHistory.listQuotes();\n    if (!result.ok) {");
    patchRegex("app.js",
      /    return \{ ok: true, authority: "server", envelope, requested: result\.quotes\.length \};/,
      '    staleServerEnvelope = envelope;\n    return { ok: true, authority: "server", envelope, requested: result.quotes.length };');
  }],
  ["M7a restore bypasses the QuoteCore normalization boundary", () => {
    patchRegex("quote-history-server.js",
      /    return Core\.normalizeDraft\(\{\n      schemaVersion: Core\.SCHEMA_VERSION,[\s\S]*?\n    \}\);\n  \}/,
      "    return snapshot;\n  }");
  }],
  ["M7b the history card renders the server's persisted total", () => {
    patch("quote-history-server.js",
      "      quoteCoreRecalculationRequired: row.quote_core_recalculation_required === true\n    };",
      "      quoteCoreRecalculationRequired: row.quote_core_recalculation_required === true,\n" +
      '      storedTotals: row.totals && typeof row.totals === "object" ? row.totals : null\n    };');
    patch("app.js",
      "        totalsAuthority: detail.quote.totalsAuthority,",
      "        totalsAuthority: detail.quote.totalsAuthority,\n        totals: detail.quote.storedTotals || null,");
    patch("quote-history.js",
      "      entries.push({\n        id: entry.id.trim().slice(0, 120),\n        savedAt: entry.savedAt.trim().slice(0, 80),\n        draft: draft\n      });",
      "      entries.push({\n        id: entry.id.trim().slice(0, 120),\n        savedAt: entry.savedAt.trim().slice(0, 80),\n" +
      '        draft: draft,\n        totals: entry.totals && typeof entry.totals === "object" ? entry.totals : null\n      });');
    patch("quote-history.js",
      "        itemCount: entry.draft.items.length,\n        grand: totals.grand",
      "        itemCount: entry.draft.items.length,\n        grand: entry.totals ? entry.totals.grand : totals.grand");
  }],
  ["M7c the save payload starts carrying totals", () => {
    patch("quote-history-server.js",
      "    if (normalized.meta.projectName) snapshot.projectName = normalized.meta.projectName;",
      "    if (normalized.meta.projectName) snapshot.projectName = normalized.meta.projectName;\n" +
      "    snapshot.totals = Core.computeDraftTotals(normalized);");
  }]
];

console.log("CI test list: " + TESTS.length + " files");
const survivors = [];
for (const [label, mutate] of MUTATIONS) {
  resetTree();
  try {
    mutate();
  } catch (err) {
    survivors.push(label);
    console.log("ERROR   " + label + " -> " + err.message);
    continue;
  }
  const killers = runSuite();
  if (killers.length === 0) survivors.push(label);
  console.log((killers.length ? "KILLED   " : "SURVIVED ") + label + "  -> " + (killers.join(", ") || "(none)"));
}
console.log("");
console.log("PREVIOUS_FALSE_GREEN_MUTATIONS=" + MUTATIONS.length);
console.log("POST_CORRECTION_MUTATION_SURVIVORS=" + survivors.length);
fs.rmSync(SCRATCH, { recursive: true, force: true });
process.exitCode = survivors.length === 0 ? 0 : 1;