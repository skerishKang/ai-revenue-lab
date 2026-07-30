/*  issue285-browser-evidence.mjs  —  Issue #285 visual evidence capture
 *
 *  Standalone Playwright script (node tests/issue285-browser-evidence.mjs).
 *  Serves the console statically, captures desktop (1440x1000) and mobile
 *  (390x844) evidence at the CURRENT git head, and fails on any console
 *  error, page error, CSP violation, horizontal overflow, unexpected
 *  failed asset, or missing required UI behavior.
 *
 *  Set EVIDENCE_BASE (e.g. http://127.0.0.1:8788/) to capture against a
 *  running `wrangler pages dev` server instead of the built-in static
 *  server; that path also exercises /api/github-status fallback routing.
 *  The credential-less environment makes /api/github-status return 503;
 *  exactly that response is counted as expectedNoise. ANY other 4xx/5xx
 *  (including favicon 404) is a hard failure.
 *
 *  Output: tests/evidence/issue285/<git-sha>/*.png + summary.json
 */

import { chromium } from "playwright";
import { spawn as spawnProcess, execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PORT = 4173;
const BASE = process.env.EVIDENCE_BASE || `http://127.0.0.1:${PORT}/`;

const gitSha = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf-8" }).trim();
const outDir = path.join(ROOT, "tests", "evidence", "issue285", gitSha);
mkdirSync(outDir, { recursive: true });

const VIEWPORTS = [
  { name: "desktop-1440x1000", width: 1440, height: 1000 },
  { name: "mobile-390x844", width: 390, height: 844 },
];

const BUSINESS_SPOTS = [1, 6, 15, 23, 32, 39, 40, 41, 42, 43, 55];
const REQUIRED_IDENTITY_ROWS = [15, 39, 40, 41, 42, 43];

function startServer() {
  const server = spawnProcess("python3", ["-m", "http.server", String(PORT), "--bind", "127.0.0.1"], { cwd: ROOT, stdio: "ignore" });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("static server did not start")), 10000);
    const poll = setInterval(async () => {
      try {
        const res = await fetch(BASE);
        if (res.ok) { clearInterval(poll); clearTimeout(timer); resolve(server); }
      } catch { /* not up yet */ }
    }, 200);
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(`EVIDENCE_ASSERTION_FAILED: ${message}`);
}

async function gotoView(page, viewName) {
  const isMobile = page.viewportSize().width < 768;
  if (isMobile) {
    await page.click("#menu-toggle");
    await page.waitForSelector("#sidebar.is-open", { timeout: 5000 });
    assert(await page.locator("#drawer-overlay.is-visible").count() === 1, "mobile drawer overlay became visible");
  }
  await page.click(`.view-nav-item[data-view="${viewName}"]`);
  await page.waitForSelector(`.view-nav-item[data-view="${viewName}"].is-active`, { timeout: 5000 });
  if (isMobile) {
    await page.waitForFunction(() => !document.querySelector("#sidebar.is-open"), { timeout: 5000 });
    assert(await page.locator("#drawer-overlay.is-visible").count() === 0, "mobile drawer auto-closed after view change");
  }
  await page.waitForTimeout(400);
}

async function captureViewport(browser, viewport) {
  const consoleErrors = [];
  const pageErrors = [];
  const failedUrls = [];
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  const page = await context.newPage();
  await page.addInitScript(() => {
    window.__cspViolations = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      window.__cspViolations.push(`${e.violatedDirective} blocked=${e.blockedURI}`);
    });
  });
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("response", (res) => { if (res.status() >= 400) failedUrls.push(`${res.status()} ${res.url()}`); });

  await page.goto(BASE, { waitUntil: "networkidle", timeout: 20000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-01-projects.png`), fullPage: true });

  await gotoView(page, "business");
  await page.waitForSelector(".biz-item", { timeout: 10000 });
  const rows = await page.locator(".biz-item").count();
  assert(rows >= 55, `expected >= 55 business rows, got ${rows}`);
  for (const n of REQUIRED_IDENTITY_ROWS) {
    assert(await page.locator(`.biz-item[data-biz-number="${n}"]`).count() === 1, `Business ${n} identity row present`);
  }
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-02-business-index.png`), fullPage: true });

  for (const n of BUSINESS_SPOTS) {
    const row = page.locator(`.biz-item[data-biz-number="${n}"]`);
    if (await row.count() === 0) continue;
    await row.scrollIntoViewIfNeeded();
  }
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-03-business-spots.png`), fullPage: true });

  const dialogRow = page.locator('.biz-item[data-biz-number="15"]');
  assert(await dialogRow.count() === 1, "Business 15 row exists for dialog capture");
  await dialogRow.scrollIntoViewIfNeeded();
  await dialogRow.click();
  await page.waitForSelector("#business-dialog[open]", { timeout: 5000 });
  assert(await page.locator("#business-dialog[open]").count() === 1, "Business 15 dialog opened");
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-04-business-15-dialog.png`) });
  await page.click("#biz-dialog-close-btn");
  await page.waitForFunction(() => !document.querySelector("#business-dialog[open]"), { timeout: 5000 });

  await gotoView(page, "search");
  await page.fill("#sf-search-input", "ai");
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-05-search.png`), fullPage: true });

  await page.click("#lang-en");
  await page.waitForFunction(() => document.documentElement.lang === "en", { timeout: 5000 });
  assert(await page.locator("#lang-en.is-active").count() === 1, "EN language button became active");
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-06-language-en.png`), fullPage: true });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  const cspViolations = await page.evaluate(() => window.__cspViolations);
  await context.close();
  return { viewport: viewport.name, rows, consoleErrors, pageErrors, overflow, failedUrls, cspViolations };
}

const server = process.env.EVIDENCE_BASE ? null : await startServer();
let exitCode = 0;
try {
  const browser = await chromium.launch();
  const results = [];
  for (const viewport of VIEWPORTS) {
    try {
      results.push(await captureViewport(browser, viewport));
    } catch (err) {
      results.push({ viewport: viewport.name, rows: 0, consoleErrors: [], pageErrors: [String(err)], overflow: false, failedUrls: [], cspViolations: [] });
    }
  }
  await browser.close();

  const summary = { gitSha, capturedAt: new Date().toISOString(), base: BASE, results };
  writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  for (const r of results) {
    r.realConsoleErrors = r.consoleErrors.filter((e) => !e.startsWith("Failed to load resource"));
    r.expectedNoiseUrls = r.failedUrls.filter((u) => u.startsWith("503 ") && u.includes("/api/github-status"));
    r.unexpectedFailedUrls = r.failedUrls.filter((u) => !(u.startsWith("503 ") && u.includes("/api/github-status")));
    r.favicon404 = r.failedUrls.filter((u) => u.includes("favicon"));
    r.expectedNoise = (r.consoleErrors.length - r.realConsoleErrors.length) + r.expectedNoiseUrls.length;
    const ok = r.realConsoleErrors.length === 0
      && r.unexpectedFailedUrls.length === 0
      && r.favicon404.length === 0
      && r.pageErrors.length === 0
      && r.cspViolations.length === 0
      && !r.overflow
      && r.rows >= 55;
    if (!ok) exitCode = 1;
    console.log(`${ok ? "PASS" : "FAIL"} ${r.viewport}: rows=${r.rows} consoleErrors=${r.realConsoleErrors.length} pageErrors=${r.pageErrors.length} cspViolations=${r.cspViolations.length} favicon404=${r.favicon404.length} overflow=${r.overflow} expectedNoise=${r.expectedNoise}`);
    for (const e of [...r.realConsoleErrors, ...r.pageErrors]) console.log(`  error: ${e}`);
    for (const u of r.unexpectedFailedUrls) console.log(`  failed: ${u}`);
    for (const v of r.cspViolations) console.log(`  csp: ${v}`);
  }
  console.log(`evidence: ${outDir}`);
} finally {
  if (server) server.kill();
}
process.exit(exitCode);
