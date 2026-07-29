/*  issue285-browser-evidence.mjs  —  Issue #285 visual evidence capture
 *
 *  Standalone Playwright script (node tests/issue285-browser-evidence.mjs).
 *  Serves the console statically, captures desktop (1440x1000) and mobile
 *  (390x844) evidence at the CURRENT git head, and fails on any console
 *  error, page error, or horizontal overflow.
 *
 *  Set EVIDENCE_BASE (e.g. http://127.0.0.1:8788/) to capture against a
 *  running `wrangler pages dev` server instead of the built-in static
 *  server; that path also exercises /api/github-status fallback routing.
 *  Browser network-stack logs for /api/github-status (503 in the
 *  credential-less environment) are counted as expectedNoise, not errors.
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

async function gotoView(page, viewName) {
  if (page.viewportSize().width < 768) {
    await page.click("#menu-toggle");
    await page.waitForTimeout(300);
  }
  await page.click(`.view-nav-item[data-view="${viewName}"]`);
  await page.waitForTimeout(400);
}

async function captureViewport(browser, viewport) {
  const consoleErrors = [];
  const pageErrors = [];
  const failedUrls = [];
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  const page = await context.newPage();
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
  page.on("pageerror", (err) => pageErrors.push(String(err)));
  page.on("response", (res) => { if (res.status() >= 400) failedUrls.push(`${res.status()} ${res.url()}`); });

  await page.goto(BASE, { waitUntil: "networkidle", timeout: 20000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-01-projects.png`), fullPage: true });

  await gotoView(page, "business");
  await page.waitForSelector(".biz-item", { timeout: 10000 });
  const rows = await page.locator(".biz-item").count();
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-02-business-index.png`), fullPage: true });

  for (const n of BUSINESS_SPOTS) {
    const row = page.locator(`.biz-item[data-biz-number="${n}"]`);
    if (await row.count() === 0) continue;
    await row.scrollIntoViewIfNeeded();
  }
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-03-business-spots.png`), fullPage: true });

  const dialogRow = page.locator('.biz-item[data-biz-number="15"]');
  if (await dialogRow.count() > 0) {
    await dialogRow.scrollIntoViewIfNeeded();
    await dialogRow.click();
    await page.waitForSelector("#business-dialog[open]", { timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(outDir, `${viewport.name}-04-business-15-dialog.png`) });
    await page.click("#biz-dialog-close-btn").catch(() => {});
  }

  await gotoView(page, "search");
  await page.fill("#sf-search-input", "ai");
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-05-search.png`), fullPage: true });

  await page.click("#lang-en");
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(outDir, `${viewport.name}-06-language-en.png`), fullPage: true });

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  await context.close();
  return { viewport: viewport.name, rows, consoleErrors, pageErrors, overflow, failedUrls };
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
      results.push({ viewport: viewport.name, rows: 0, consoleErrors: [], pageErrors: [String(err)], overflow: false, failedUrls: [] });
    }
  }
  await browser.close();

  const summary = { gitSha, capturedAt: new Date().toISOString(), base: BASE, results };
  writeFileSync(path.join(outDir, "summary.json"), JSON.stringify(summary, null, 2));
  for (const r of results) {
    r.realConsoleErrors = r.consoleErrors.filter((e) => !e.startsWith("Failed to load resource"));
    r.unexpectedFailedUrls = r.failedUrls.filter((u) => !u.includes("/api/github-status"));
    r.expectedNoise = (r.consoleErrors.length - r.realConsoleErrors.length) + (r.failedUrls.length - r.unexpectedFailedUrls.length);
    const ok = r.realConsoleErrors.length === 0 && r.unexpectedFailedUrls.length === 0 && r.pageErrors.length === 0 && !r.overflow && r.rows >= 55;
    if (!ok) exitCode = 1;
    console.log(`${ok ? "PASS" : "FAIL"} ${r.viewport}: rows=${r.rows} consoleErrors=${r.realConsoleErrors.length} pageErrors=${r.pageErrors.length} overflow=${r.overflow} expectedNoise=${r.expectedNoise}`);
    for (const e of [...r.realConsoleErrors, ...r.pageErrors]) console.log(`  error: ${e}`);
    for (const u of r.unexpectedFailedUrls) console.log(`  failed: ${u}`);
  }
  console.log(`evidence: ${outDir}`);
} finally {
  if (server) server.kill();
}
process.exit(exitCode);
