/* browser_check.js — 파디엠 v2 browser validation + captures (Playwright)
   Run from workspace: NODE_PATH=<playwright node_modules> node tests/browser_check.js */
"use strict";
var http = require("http"), fs = require("fs"), path = require("path");
var SRC = path.resolve(__dirname, "..");
var OUT = path.join(SRC, "evidence");
var MIME = { ".html":"text/html; charset=utf-8", ".css":"text/css; charset=utf-8", ".js":"text/javascript; charset=utf-8", ".jpg":"image/jpeg", ".png":"image/png", ".svg":"image/svg+xml" };

function serve(port) {
  return new Promise(function (resolve) {
    var server = http.createServer(function (req, res) {
      var p = decodeURIComponent(req.url.split("?")[0]);
      if (p === "/") p = "/index.html";
      var f = path.join(SRC, p);
      if (!f.startsWith(SRC) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end("nf"); return; }
      res.writeHead(200, { "Content-Type": MIME[path.extname(f)] || "application/octet-stream" });
      fs.createReadStream(f).pipe(res);
    });
    server.listen(port, "127.0.0.1", function () { resolve(server); });
  });
}
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

var STATES = ["home", "diagnostic", "case", "workflow", "offers", "deliverables", "conversion"];

(async function () {
  var playwright = require("playwright");
  var server = await serve(8760);
  var base = "http://127.0.0.1:8760/";
  fs.mkdirSync(OUT, { recursive: true });
  var browser = await playwright.chromium.launch({ headless: true });
  var report = { results: [], captures: [] };
  var allOk = true;

  var viewports = [
    { name: "desktop", width: 1440, height: 1100 },
    { name: "tablet", width: 768, height: 1024 },
    { name: "mobile", width: 390, height: 844 },
  ];

  for (var vi = 0; vi < viewports.length; vi++) {
    var vp = viewports[vi];
    var ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    var page = await ctx.newPage();
    var consoleErrors = [], pageErrors = [], failed = [], external = [];
    page.on("console", function (m) { if (m.type() === "error") consoleErrors.push(m.text()); });
    page.on("pageerror", function (e) { pageErrors.push(String(e)); });
    page.on("requestfailed", function (r) { failed.push(r.url()); });
    page.on("request", function (r) { if (/^https?:/.test(r.url()) && r.url().indexOf("127.0.0.1") === -1) external.push(r.url()); });

    var r = await page.goto(base, { waitUntil: "load", timeout: 60000 });
    await page.waitForSelector("#hero-title");
    await sleep(1500);

    var overflow = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2");
    // diagnostic journey
    await page.selectOption("select[name=task]", "publishing");
    await page.selectOption("select[name=ai]", "individual");
    await page.click("[data-diag-run]");
    await sleep(400);
    var diagOk = (await page.locator("#diag-result h3").count()) === 1;
    // case-study + offers + deliverables + conversion journeys
    await page.click('[data-conv="proposal"]');
    await sleep(300);
    var convOk = (await page.locator("#conv-result h3").count()) === 1;
    await page.locator('[data-del="blueprint"]').first().click();
    await sleep(300);
    var delOk = (await page.locator("#del-detail h3").count()) === 1;
    // workflow signature motion (classes applied)
    await page.click("[data-wf-run]");
    await sleep(3500);
    var wfOk = await page.evaluate("document.querySelector('[data-wf-step=\"a4\"]').classList.contains('is-review') && document.querySelector('[data-wf-seal]').textContent.indexOf('HUMAN-APPROVED') === 0");

    var res = { viewport: vp.name, http: r.status(), consoleErrors: consoleErrors.length, pageErrors: pageErrors.length,
      failed: failed.length, external: external.length, overflow: overflow, diagnostic: diagOk, conversion: convOk,
      deliverable: delOk, workflowMotion: wfOk };
    report.results.push(res);
    allOk = allOk && res.http === 200 && res.consoleErrors === 0 && res.pageErrors === 0 && res.failed === 0 &&
      res.external === 0 && !res.overflow && res.diagnostic && res.conversion && res.deliverable && res.workflowMotion;
    console.log("[" + vp.name + "] http=" + res.http + " console=" + res.consoleErrors + " page=" + res.pageErrors +
      " failed=" + res.failed + " external=" + res.external + " overflow=" + res.overflow + " diag=" + res.diagnostic +
      " conv=" + res.conversion + " del=" + res.deliverable + " wf=" + res.workflowMotion + (allOk ? " OK" : " FAIL"));

    // captures for this viewport
    for (var s = 0; s < STATES.length; s++) {
      await page.goto(base + "#" + (STATES[s] === "home" ? "hero" : STATES[s]), { waitUntil: "load" });
      await sleep(600);
      var shot = path.join(OUT, vp.name + "-" + STATES[s] + ".png");
      await page.screenshot({ path: shot });
      report.captures.push(shot);
    }
    await ctx.close();
  }

  // keyboard + focus check on desktop
  var kctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  var kpage = await kctx.newPage();
  await kpage.goto(base, { waitUntil: "load" });
  await kpage.keyboard.press("Tab");
  var focused = await kpage.evaluate("document.activeElement.tagName");
  report.keyboardFirstFocus = focused;
  allOk = allOk && focused !== "BODY";

  // back/forward stability
  await kpage.goto(base + "#case", { waitUntil: "load" });
  await kpage.goto(base + "#offers", { waitUntil: "load" });
  await kpage.goBack();
  await sleep(400);
  var hashAfterBack = await kpage.evaluate("location.hash");
  report.backForward = hashAfterBack;
  await kctx.close();

  // reduced motion emulation
  var rctx = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
  var rpage = await rctx.newPage();
  await rpage.goto(base, { waitUntil: "load" });
  await rpage.click("[data-wf-run]");
  await sleep(200);
  var rf = await rpage.evaluate("document.querySelector('[data-wf-seal]').textContent");
  report.reducedMotionFinal = rf;
  await rctx.close();

  // videos
  var vctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: path.join(OUT, "vid-desktop"), size: { width: 1440, height: 900 } } });
  var vpage = await vctx.newPage();
  await vpage.goto(base, { waitUntil: "load" });
  await sleep(500);
  for (var i = 0; i < STATES.length; i++) { await vpage.goto(base + "#" + (STATES[i] === "home" ? "hero" : STATES[i]), { waitUntil: "load" }); await sleep(900); }
  await vpage.click("[data-wf-run]"); await sleep(3400);
  await vctx.close();

  var mv = await browser.newContext({ viewport: { width: 390, height: 844 }, recordVideo: { dir: path.join(OUT, "vid-mobile"), size: { width: 390, height: 844 } } });
  var mp = await mv.newPage();
  await mp.goto(base, { waitUntil: "load" }); await sleep(500);
  await mp.click("[data-wf-run]"); await sleep(3400);
  await mp.goto(base + "#diagnostic", { waitUntil: "load" }); await sleep(800);
  await mv.close();

  var wctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: path.join(OUT, "vid-wf"), size: { width: 1440, height: 900 } } });
  var wp = await wctx.newPage();
  await wp.goto(base + "#workflow", { waitUntil: "load" }); await sleep(400);
  await wp.click("[data-wf-run]"); await sleep(3600);
  await wctx.close();

  await browser.close();
  server.close();

  fs.writeFileSync(path.join(OUT, "browser-check.json"), JSON.stringify(report, null, 2));
  console.log(allOk ? "BROWSER_VALIDATION_PASS" : "BROWSER_VALIDATION_FAIL");
  process.exit(allOk ? 0 : 1);
})().catch(function (e) { console.error(e); process.exit(2); });
