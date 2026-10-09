"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const Runner = require("./run-b66-contracts.cjs");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "b66-test-discovery-"));
try {
  const tests = path.join(root, "tests");
  fs.mkdirSync(tests);
  fs.mkdirSync(path.join(tests, "nested"));
  fs.writeFileSync(path.join(root, "product.js"), "module.exports = 1;\n");
  fs.writeFileSync(path.join(root, "other.js"), "module.exports = 2;\n");
  fs.writeFileSync(path.join(tests, "alpha.test.cjs"), "process.exit(0);\n");
  fs.writeFileSync(path.join(tests, "beta.test.mjs"), "process.exit(0);\n");
  fs.writeFileSync(path.join(tests, "nested", "gamma.test.js"), "process.exit(0);\n");
  fs.writeFileSync(path.join(tests, "helper.cjs"), "throw Error('not a test');\n");

  assert.deepEqual(Runner.discoverSourceScripts(root), ["other.js", "product.js"]);
  assert.deepEqual(Runner.discoverTestFiles(tests), [
    "alpha.test.cjs", "beta.test.mjs", "nested/gamma.test.js"
  ]);
  const calls = [];
  const invoke = (args, cwd) => {
    calls.push({ args, cwd });
  };
  assert.deepEqual(Runner.runSuite("--all", { sourceDir: root, testsDir: tests, invoke }),
    { scripts: 2, tests: 3 });
  assert.deepEqual(calls.map(item => item.args[0]), [
    "--check", "--check",
    path.join("tests", "alpha.test.cjs"),
    path.join("tests", "beta.test.mjs"),
    path.join("tests", "nested/gamma.test.js")
  ]);
  assert.ok(calls.every(item => item.cwd === root));
  assert.throws(() => Runner.runSuite("--unknown", { sourceDir: root, testsDir: tests, invoke }),
    /B66_INVALID_TEST_MODE/);

  // A newly created test is automatically discovered without editing YAML.
  fs.writeFileSync(path.join(tests, "delta.test.cjs"), "process.exit(0);\n");
  assert.equal(Runner.discoverTestFiles(tests).length, 4);

  // A failed child test must fail the whole suite. No false-green summaries.
  assert.throws(
    () => Runner.runSuite("--tests", {
      sourceDir: root, testsDir: tests,
      invoke: () => { throw new Error("B66_COMMAND_FAILED"); }
    }),
    /B66_COMMAND_FAILED/
  );
  // Real subprocess negative canaries (no products or credentials mutated).
  // Broken tests and malformed JS must fail the canonical runner, not just a
  // fake injected callback. Isolated temp files are deleted in finally.
  const invokeRealQuietly = (args, cwd) => {
    const child = spawnSync(process.execPath, args, {
      cwd, shell: false, encoding: "utf8", timeout: 10000
    });
    if (child.error || child.signal || child.status !== 0) {
      throw new Error("B66_COMMAND_FAILED: " + args.join(" "));
    }
  };
  const failingTest = path.join(tests, "zz-negative-canary.test.cjs");
  fs.writeFileSync(failingTest, "throw new Error('deliberate_test_failure');\\n".replace(/\\n/g, "\n"));
  try {
    assert.throws(() => Runner.runSuite("--tests", {
      sourceDir: root, testsDir: tests, invoke: invokeRealQuietly
    }), /B66_COMMAND_FAILED: tests[/\\]zz-negative-canary\\.test\\.cjs/);
    console.log("B66_REAL_TEST_FAILURE_PROPAGATES=PASS");
  } finally {
    fs.unlinkSync(failingTest);
  }
  const brokenSource = path.join(root, "zz-negative-canary.js");
  fs.writeFileSync(brokenSource, "const invalid = ;\n");
  try {
    assert.throws(() => Runner.runSuite("--syntax", {
      sourceDir: root, testsDir: tests, invoke: invokeRealQuietly
    }), /B66_COMMAND_FAILED: --check zz-negative-canary\\.js/);
    console.log("B66_REAL_SYNTAX_FAILURE_PROPAGATES=PASS");
  } finally {
    fs.unlinkSync(brokenSource);
  }

  console.log("B66_TEST_DISCOVERY_NEGATIVE_AND_POSITIVE=PASS");
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
