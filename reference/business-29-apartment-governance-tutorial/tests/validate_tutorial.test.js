/*  validate_tutorial.test.js  —  repository-local Node tests (no browser)
 *
 *  Business 29 guided tutorial — de-identified synthetic.
 *  Run from repo root:
 *    node reference/business-29-apartment-governance-tutorial/tests/validate_tutorial.test.js
 */

"use strict";

var assert = require("assert");
var fs = require("fs");
var path = require("path");
var child = require("child_process");

var workspace = path.resolve(__dirname, "..");
var repoRoot = path.resolve(__dirname, "..", "..", "..");

var data = require(path.join(workspace, "scripts", "tutorial-data.js"));

var failures = [];
function check(name, fn) {
  try {
    fn();
    console.log("[PASS] " + name);
  } catch (err) {
    failures.push(name);
    console.log("[FAIL] " + name + " — " + err.message);
  }
}

function git(args) {
  return child.execSync("git " + args, { cwd: repoRoot, encoding: "utf8" });
}

var SHIP_FILES = [
  "index.html",
  "styles/main.css",
  "scripts/tutorial-data.js",
  "scripts/app.js",
  "data/tutorial-data.json",
];

function shipContent() {
  return SHIP_FILES.map(function (f) {
    return fs.readFileSync(path.join(workspace, f), "utf8");
  }).join("\n");
}

/* 1. fixture completeness */
check("fixture completeness (7 chapters, 7 scenarios)", function () {
  assert.strictEqual(data.chapters.length, 7, "exactly 7 chapters");
  assert.strictEqual(data.scenarios.length, 7, "exactly 7 scenarios");
  data.chapters.forEach(function (c) {
    assert.ok(c.id && c.title, "chapter id/title");
    assert.ok(Array.isArray(c.steps) && c.steps.length >= 2, "chapter steps: " + c.id);
    assert.ok(c.guide, "chapter guide: " + c.id);
  });
  data.scenarios.forEach(function (s) {
    assert.ok(s.id && s.title && s.text && s.status, "scenario fields: " + s.id);
  });
});

/* 2. forbidden legal judgement terms absent */
check("forbidden legal judgement terms absent", function () {
  var forbidden = ["적법", "위법", "불법", "무효", "범죄", "승소", "패소"];
  var content = shipContent();
  forbidden.forEach(function (t) {
    assert.strictEqual(content.indexOf(t), -1, "forbidden term present: " + t);
  });
});

/* 3. required guide expressions present */
check("required guide expressions present", function () {
  var required = ["확인 필요", "자료 부족", "절차 보완 필요", "공개 보류", "전문 검토 필요", "기록 유지"];
  var content = shipContent();
  required.forEach(function (t) {
    assert.ok(content.indexOf(t) !== -1, "required expression missing: " + t);
  });
});

/* 4. real apartment identity applied */
check("real apartment identity applied", function () {
  var content = shipContent();
  assert.strictEqual(data.meta.community, "방림명지로드힐아파트");
  assert.strictEqual(data.meta.communityEn, "Bangnim Myeongji Roadhill Apartment");
  assert.strictEqual(data.meta.households, 192);
  assert.strictEqual(data.meta.buildings, "101동 · 102동");
  assert.strictEqual(data.meta.council, "제5기 입주자대표회의");
  assert.strictEqual(data.meta.chair, "회장 김경애");
  ["방림명지로드힐", "192세대", "101동", "102동", "김경애", "제5기 입주자대표회의", "광주광역시 남구"].forEach(function (t) {
    assert.ok(content.indexOf(t) !== -1, "required identity text missing: " + t);
  });
  assert.ok(content.indexOf("데모 예시") !== -1, "demo example markers present");
});

/* 5. no synthetic apartment identity remains */
check("no synthetic apartment identity remains", function () {
  var forbidden = [
    "솔빛마루", "Solbit", "420", "fictional community", "가상 단지", "합성 단지",
    "synthetic apartment identity", "all community details are synthetic",
    "SYNTHETIC APARTMENT RECORDS",
  ];
  var content = shipContent();
  forbidden.forEach(function (t) {
    assert.strictEqual(content.indexOf(t), -1, "forbidden identity reference present: " + t);
  });
  assert.ok(content.indexOf("방림명지로드힐 운영 데모") !== -1, "demo boundary phrase present");
  assert.ok(content.indexOf("실제 단지 적용형 시연") !== -1, "real-complex demo phrase present");
});

/* 5. data.js mirrors data.json */
check("tutorial-data.js mirrors data/tutorial-data.json", function () {
  var json = JSON.parse(fs.readFileSync(path.join(workspace, "data", "tutorial-data.json"), "utf8"));
  assert.deepStrictEqual(data, json);
});

/* 6. external runtime dependency 0 */
check("external runtime dependency 0", function () {
  SHIP_FILES.forEach(function (f) {
    var content = fs.readFileSync(path.join(workspace, f), "utf8");
    var m = content.match(/https?:\/\//g);
    assert.ok(!m, f + " contains external URL(s): " + (m || []).join(","));
  });
});

/* 6b. no word-split source patterns / mixed English */
check("no word-split source patterns or mixed English", function () {
  var content = shipContent();
  ["의결 authority", "authority는", "공\n개", "운\n영실", "가이\n드"].forEach(function (t) {
    assert.strictEqual(content.indexOf(t), -1, "forbidden pattern present: " + JSON.stringify(t));
  });
  assert.ok(content.indexOf("가이드") !== -1, "가이드 present as a whole word");
  assert.ok(content.indexOf("운영실") !== -1, "운영실 present as a whole word");
  assert.ok(content.indexOf("공개") !== -1, "공개 present as a whole word");
});

/* 7. JavaScript syntax */
check("JavaScript syntax", function () {
  ["scripts/tutorial-data.js", "scripts/app.js"].forEach(function (f) {
    var r = child.spawnSync(process.execPath, ["--check", path.join(workspace, f)], { encoding: "utf8" });
    assert.strictEqual(r.status, 0, f + " syntax error: " + r.stderr);
  });
});

/* 8. index.html semantics */
check("index.html semantics", function () {
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  var app = fs.readFileSync(path.join(workspace, "scripts", "app.js"), "utf8");
  assert.ok(html.indexOf('lang="ko"') !== -1, "lang ko");
  assert.ok(html.indexOf('class="skip-link"') !== -1, "skip link");
  assert.ok(html.indexOf('role="tablist"') !== -1, "tablist");
  assert.ok(app.indexOf('role="tab"') !== -1, "tab role rendered by app.js");
  assert.ok(app.indexOf("aria-selected") !== -1, "aria-selected set by app.js");
  assert.ok(html.indexOf("tabindex") !== -1, "focusable main");
  assert.ok(html.indexOf("<footer") !== -1, "footer");
});

/* 9. 390px CSS contract marker */
check("390px CSS contract marker", function () {
  var css = fs.readFileSync(path.join(workspace, "styles", "main.css"), "utf8");
  assert.ok(css.indexOf("@media(max-width: 390px)") !== -1, "390px breakpoint");
  assert.ok(css.indexOf("prefers-reduced-motion") !== -1, "reduced motion");
});

/* 10. allowed-scope check */
check("allowed-scope check (only reference/business-29-apartment-governance-tutorial/ changed)", function () {
  var diff = git("diff --name-only origin/main...HEAD").trim();
  if (diff) {
    diff.split("\n").forEach(function (p) {
      assert.ok(p.indexOf("reference/business-29-apartment-governance-tutorial/") === 0, "out-of-scope committed path: " + p);
    });
  }
  var refStatus = git("status --porcelain=v1 -z -- reference/");
  if (refStatus) {
    refStatus.split("\0").forEach(function (rec) {
      if (!rec) return;
      var p = rec.slice(3);
      assert.ok(p.indexOf("reference/business-29-apartment-governance-tutorial/") === 0, "out-of-scope reference change: " + p);
    });
  }
});

/* 11. git diff --check */
check("git diff --check clean", function () {
  var out = git("diff --check origin/main...HEAD").trim();
  assert.strictEqual(out, "", "whitespace errors in branch diff:\n" + out);
  var wd = git("diff --check").trim();
  assert.strictEqual(wd, "", "whitespace errors in working tree:\n" + wd);
});

console.log("");
if (failures.length) {
  console.log(failures.length + " check(s) failed.");
  process.exit(1);
}
console.log("All 13 Business 29 방림명지로드힐 guided tutorial checks passed.");
