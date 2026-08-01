/*  browser_check.js  —  headless browser validation (Playwright + Chromium)
 *
 *  Validates desktop/tablet/mobile viewports, console errors, page errors,
 *  failed requests, and external network requests for the guided tutorial.
 *
 *  Run from the workspace directory:
 *    node tests/browser_check.js
 *  (requires `npm install playwright` — browsers reused from cache)
 */

"use strict";

var http = require("http");
var fs = require("fs");
var path = require("path");

var WORKSPACE = path.resolve(__dirname, "..");
var OUT = path.join(WORKSPACE, "evidence", "browser-check.json");

var VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
];

function serve(port) {
  var mime = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
  };
  return new Promise(function (resolve) {
    var server = http.createServer(function (req, res) {
      var urlPath = decodeURIComponent(req.url.split("?")[0]);
      if (urlPath === "/") urlPath = "/index.html";
      var file = path.join(WORKSPACE, urlPath);
      if (!file.startsWith(WORKSPACE) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        res.writeHead(404);
        res.end("not found");
        return;
      }
      res.writeHead(200, { "Content-Type": mime[path.extname(file)] || "application/octet-stream" });
      fs.createReadStream(file).pipe(res);
    });
    server.listen(port, "127.0.0.1", function () {
      resolve(server);
    });
  });
}

(async function () {
  var playwright = require("playwright");
  var server = await serve(8741);
  var base = "http://127.0.0.1:8741/";

  var browser = await playwright.chromium.launch({ headless: true });
  var results = [];
  var allOk = true;

  for (var i = 0; i < VIEWPORTS.length; i++) {
    var vp = VIEWPORTS[i];
    var page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });

    var consoleErrors = [];
    var pageErrors = [];
    var failedRequests = [];
    var externalRequests = [];

    page.on("console", function (msg) {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", function (err) { pageErrors.push(String(err)); });
    page.on("requestfailed", function (req) { failedRequests.push(req.url() + " :: " + (req.failure() && req.failure().errorText)); });
    page.on("request", function (req) {
      var url = req.url();
      if (/^https?:\/\//.test(url) && url.indexOf("127.0.0.1") === -1) {
        externalRequests.push(url);
      }
    });

    var r = await page.goto(base, { waitUntil: "load" });
    await page.waitForSelector("#chapter-tabs button");
    // exercise interactions
    var tabCount = await page.locator("#chapter-tabs button").count();
    for (var t = 0; t < tabCount; t++) {
      await page.locator("#chapter-tabs button").nth(t).click();
      await page.waitForTimeout(40);
    }
    var optCount = await page.locator("#scenario option").count();
    for (var s = 0; s < optCount; s++) {
      await page.selectOption("#scenario", { index: s });
      await page.waitForTimeout(30);
    }
    await page.locator("#chapter-tabs button").nth(0).click();

    var title = await page.title();
    var ok =
      r.status() === 200 &&
      consoleErrors.length === 0 &&
      pageErrors.length === 0 &&
      failedRequests.length === 0 &&
      externalRequests.length === 0;

    var res = {
      viewport: vp.name,
      size: vp.width + "x" + vp.height,
      httpStatus: r.status(),
      title: title,
      consoleErrors: consoleErrors,
      pageErrors: pageErrors,
      failedRequests: failedRequests,
      externalRequests: externalRequests,
      pass: ok,
    };
    results.push(res);
    if (!ok) allOk = false;
    console.log(
      "[VIEWPORT " + vp.name + "] status=" + r.status() +
      " consoleErrors=" + consoleErrors.length +
      " pageErrors=" + pageErrors.length +
      " failed=" + failedRequests.length +
      " external=" + externalRequests.length +
      " => " + (ok ? "PASS" : "FAIL")
    );
    await page.close();
  }

  await browser.close();
  server.close();

  var summary = {
    browser: "chromium headless (Playwright)",
    run_at: new Date().toISOString(),
    viewports: results,
    pass: allOk,
  };
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(summary, null, 2));
  console.log(allOk ? "BROWSER_VALIDATION_PASS" : "BROWSER_VALIDATION_FAIL");
  process.exit(allOk ? 0 : 1);
})().catch(function (err) {
  console.error(err);
  process.exit(2);
});
