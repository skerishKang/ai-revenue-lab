/* browser_check.js — 파디엠 v2 browser validation (correction round)
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
  var server = await serve(8761);
  var base = "http://127.0.0.1:8761/";
  fs.mkdirSync(OUT, { recursive: true });
  var browser = await playwright.chromium.launch({ headless: true });
  var report = { results: [], captures: [] };
  var allOk = true;
  function ok(b) { allOk = allOk && b; return b; }

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
    await sleep(600);

    // C3: workflow NOT auto-completed before viewport entry
    var wfBefore = await page.evaluate("document.querySelector('[data-wf-step=\"a2\"]').classList.contains('is-ai')");
    var overflow = await page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2");

    // C9: diagnostic — change does NOT render, explicit run renders
    await page.selectOption("select[name=task]", "publishing");
    await sleep(200);
    var diagNoRender = (await page.locator("#diag-result h3").count()) === 0;
    await page.click("[data-diag-run]");
    await sleep(300);
    var diagRender = (await page.locator("#diag-result h3").count()) === 1;

    // C10: deliverable aria-expanded
    await page.goto(base + "#deliverables", { waitUntil: "load" });
    await sleep(400);
    await page.locator('[data-del="blueprint"]').first().click();
    await sleep(250);
    var delAria = await page.locator('[data-del="blueprint"]').first().getAttribute("aria-expanded");

    // conversion
    await page.click('[data-conv="proposal"]');
    await sleep(250);
    var convOk = (await page.locator("#conv-result h3").count()) === 1;

    // C6: nav active + aria-current (top = hero active; scroll to case -> case active + color change)
    await page.goto(base, { waitUntil: "load" });
    await sleep(400);
    var navTop = await page.evaluate("(function(){ var w=document.querySelector('[data-nav-link][href=\"#hero\"]'); return { active: w.classList.contains('is-active'), current: w.getAttribute('aria-current') }; })()");
    await page.evaluate("document.documentElement.style.scrollBehavior='auto'; window.scrollTo(0, document.getElementById('case').offsetTop);");
    await sleep(400);
    var nav = await page.evaluate("(function(){ var a=document.querySelector('.nav-links a[href=\"#case\"]'); return { active: a.classList.contains('is-active'), current: a.getAttribute('aria-current'), color: getComputedStyle(a).color }; })()");
    var navOk = navTop.active === true && navTop.current === "location" && nav.active === true &&
      nav.current === "location" && nav.color !== "rgb(216, 208, 192)";

    // C3: workflow runs once after viewport entry (scroll into view)
    await page.goto(base, { waitUntil: "load" });
    await page.waitForSelector("#hero-title");
    await page.evaluate("document.documentElement.style.scrollBehavior='auto'; document.getElementById('workflow').scrollIntoView({block:'center'});");
    await sleep(700);
    var wfEnter = await page.evaluate("document.querySelector('[data-wf-step=\"b2\"]').classList.contains('is-hot')");

    // C5: transform opacity change (hidden -> on)
    var opacityBefore = await page.evaluate("parseFloat(getComputedStyle(document.querySelector('[data-wf-transform] span')).opacity)");
    await sleep(3200);
    var opacityAfter = await page.evaluate("parseFloat(getComputedStyle(document.querySelector('[data-wf-transform] span')).opacity)");
    var sealFinal = await page.evaluate("document.querySelector('[data-wf-seal]').textContent");

    // C4: rapid replay 3x — final state correct, no orphans
    var errsBefore = pageErrors.length;
    for (var k = 0; k < 3; k++) { await page.click("[data-wf-run]"); await sleep(120); }
    await sleep(3400);
    var replaySeal = await page.evaluate("document.querySelector('[data-wf-seal]').textContent");
    var replayOk = replaySeal.indexOf("HUMAN-APPROVED AI MEDIA") === 0 && pageErrors.length === errsBefore && !wfBefore;

    var res = { viewport: vp.name, http: r.status(), consoleErrors: consoleErrors.length, pageErrors: pageErrors.length,
      failed: failed.length, external: external.length, overflow: overflow,
      wfNotStartedBeforeEntry: !wfBefore, diagNoRenderOnChange: diagNoRender, diagRenderOnRun: diagRender,
      deliverableAria: delAria, conversion: convOk, navActive: navOk, wfRunOnceAfterEntry: wfEnter,
      transformOpacityBefore: opacityBefore, transformOpacityAfter: opacityAfter, replayOk: replayOk };
    report.results.push(res);
    var good = ok(res.http === 200 && res.consoleErrors === 0 && res.pageErrors === 0 && res.failed === 0 &&
      res.external === 0 && !res.overflow && res.wfNotStartedBeforeEntry && res.diagNoRenderOnChange &&
      res.diagRenderOnRun && res.deliverableAria === "true" && res.conversion && res.navActive && res.wfRunOnceAfterEntry &&
      res.transformOpacityBefore === 0 && res.transformOpacityAfter === 1 && res.replayOk);
    console.log("[" + vp.name + "] " + JSON.stringify(res) + " " + (good ? "OK" : "FAIL"));

    // captures: 7 states at this viewport (new head)
    for (var s = 0; s < STATES.length; s++) {
      await page.goto(base + "#" + (STATES[s] === "home" ? "hero" : STATES[s]), { waitUntil: "load" });
      await sleep(450);
      var shot = path.join(OUT, vp.name + "-" + STATES[s] + ".png");
      await page.screenshot({ path: shot });
      report.captures.push(shot);
    }
    await ctx.close();
  }

  // workflow stage captures (desktop 1440x1100): before / mid / final
  var wctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  var wp = await wctx.newPage();
  await wp.goto(base, { waitUntil: "load" });
  await wp.waitForSelector("#hero-title");
  await wp.evaluate("document.getElementById('workflow').scrollIntoView({block:'center'})");
  await sleep(120);
  await wp.locator("#workflow").screenshot({ path: path.join(OUT, "workflow-before.png") });
  report.captures.push(path.join(OUT, "workflow-before.png"));
  await sleep(2000);
  await wp.locator("#workflow").screenshot({ path: path.join(OUT, "workflow-mid.png") });
  report.captures.push(path.join(OUT, "workflow-mid.png"));
  await sleep(1500);
  await wp.locator("#workflow").screenshot({ path: path.join(OUT, "workflow-final.png") });
  report.captures.push(path.join(OUT, "workflow-final.png"));
  await wctx.close();

  // reduced-motion final
  var rctx = await browser.newContext({ viewport: { width: 1440, height: 1100 }, reducedMotion: "reduce" });
  var rp = await rctx.newPage();
  await rp.goto(base, { waitUntil: "load" });
  await sleep(400);
  await rp.locator("#workflow").screenshot({ path: path.join(OUT, "workflow-reduced-motion-final.png") });
  report.captures.push(path.join(OUT, "workflow-reduced-motion-final.png"));
  var rmSeal = await rp.evaluate("document.querySelector('[data-wf-seal]').textContent");
  report.reducedMotionSeal = rmSeal;
  ok(rmSeal.indexOf("HUMAN-APPROVED AI MEDIA") === 0);
  await rctx.close();

  // keyboard: mobile rail reachable via Tab on mobile
  var mctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  var mp = await mctx.newPage();
  await mp.goto(base, { waitUntil: "load" });
  await sleep(400);
  var railVisible = await mp.evaluate("(function(){ var r=document.querySelector('.mobile-rail'); return r && getComputedStyle(r).display !== 'none'; })()");
  var railOverflow = await mp.evaluate("(function(){ var r=document.querySelector('.mobile-rail'); return r ? r.scrollWidth > r.clientWidth : false; })()");
  // keyboard reach rail link
  var railFocused = false;
  for (var t = 0; t < 12; t++) { await mp.keyboard.press("Tab"); var tag = await mp.evaluate("document.activeElement.getAttribute('href')"); if (tag === "#diagnostic") { railFocused = true; break; } }
  report.mobileRail = { visible: railVisible, scrollableWhenNeeded: railOverflow, keyboardReachable: railFocused };
  ok(railVisible && railFocused);
  var mobOverflow = await mp.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2");
  report.mobileOverflow = mobOverflow;
  ok(!mobOverflow);
  await mctx.close();

  // videos (new head)
  function renameVideo(dir, target) {
    var files = fs.readdirSync(path.join(OUT, dir)).filter(function (f) { return f.endsWith(".webm"); });
    if (files.length) { fs.renameSync(path.join(OUT, dir, files[0]), path.join(OUT, target)); fs.rmSync(path.join(OUT, dir), { recursive: true, force: true }); return true; }
    return false;
  }
  var vd = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: path.join(OUT, "vd"), size: { width: 1440, height: 900 } } });
  var vp2 = await vd.newPage();
  await vp2.goto(base, { waitUntil: "load" }); await sleep(500);
  for (var st2 = 0; st2 < STATES.length; st2++) { await vp2.goto(base + "#" + (STATES[st2] === "home" ? "hero" : STATES[st2]), { waitUntil: "load" }); await sleep(800); }
  await vp2.evaluate("document.documentElement.style.scrollBehavior='auto'; document.getElementById('workflow').scrollIntoView({block:'center'});");
  await sleep(3600);
  await vd.close(); renameVideo("vd", "desktop-primary-journey.webm");

  var vm = await browser.newContext({ viewport: { width: 390, height: 844 }, recordVideo: { dir: path.join(OUT, "vm"), size: { width: 390, height: 844 } } });
  var vmp = await vm.newPage();
  await vmp.goto(base, { waitUntil: "load" }); await sleep(500);
  await vmp.evaluate("document.documentElement.style.scrollBehavior='auto'; document.getElementById('workflow').scrollIntoView({block:'center'});");
  await sleep(3600);
  await vmp.goto(base + "#diagnostic", { waitUntil: "load" }); await sleep(800);
  await vm.close(); renameVideo("vm", "mobile-primary-journey.webm");

  var vw = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: path.join(OUT, "vw"), size: { width: 1440, height: 900 } } });
  var vwp = await vw.newPage();
  await vwp.goto(base + "#workflow", { waitUntil: "load" }); await sleep(400);
  await vwp.click("[data-wf-run]"); await sleep(3600);
  await vw.close(); renameVideo("vw", "workflow-transformation-motion.webm");

  await browser.close();
  server.close();
  fs.writeFileSync(path.join(OUT, "browser-check.json"), JSON.stringify(report, null, 2));
  console.log(allOk ? "BROWSER_VALIDATION_PASS" : "BROWSER_VALIDATION_FAIL");
  process.exit(allOk ? 0 : 1);
})().catch(function (e) { console.error(e); process.exit(2); });
