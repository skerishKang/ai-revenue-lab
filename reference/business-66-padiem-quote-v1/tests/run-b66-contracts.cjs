"use strict";

// Canonical B66 offline test runner. No network, credentials or Production actions.
// All top-level product JavaScript is syntax checked; every *.test.{cjs,mjs,js}
// anywhere under tests/ is executed in an independent Node process.
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const SOURCE_DIR = path.resolve(__dirname, "..");
const TEST_DIR = __dirname;
const TEST_PATTERN = /\.test\.(?:cjs|mjs|js)$/;

function discoverTestFiles(root = TEST_DIR) {
  const files = [];
  function walk(dir, relative) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const name = relative ? relative + "/" + entry.name : entry.name;
      if (entry.isDirectory()) walk(path.join(dir, entry.name), name);
      else if (entry.isFile() && TEST_PATTERN.test(entry.name)) files.push(name);
    }
  }
  walk(root, "");
  return files.sort();
}

function discoverSourceScripts(root = SOURCE_DIR) {
  return fs.readdirSync(root, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.endsWith(".js"))
    .map(entry => entry.name).sort();
}

function invokeNode(args, cwd) {
  const result = spawnSync(process.execPath, args, {
    cwd, stdio: "inherit", shell: false
  });
  if (result.error || result.signal || result.status !== 0) {
    throw new Error("B66_COMMAND_FAILED: " + args.join(" ") +
      " (exit=" + String(result.status) + ", signal=" + String(result.signal) + ")");
  }
}

function runSuite(mode, options = {}) {
  if (!["--all", "--syntax", "--tests"].includes(mode)) {
    throw new Error("B66_INVALID_TEST_MODE: " + String(mode));
  }
  const sourceDir = options.sourceDir || SOURCE_DIR;
  const testsDir = options.testsDir || path.join(sourceDir, "tests");
  const invoke = options.invoke || invokeNode;
  let scripts = 0;
  let tests = 0;
  if (mode === "--all" || mode === "--syntax") {
    const names = discoverSourceScripts(sourceDir);
    if (names.length === 0) throw new Error("B66_NO_PRODUCT_JS");
    for (const name of names) {
      invoke(["--check", name], sourceDir);
      scripts++;
    }
  }
  if (mode === "--all" || mode === "--tests") {
    const names = discoverTestFiles(testsDir);
    if (names.length === 0) throw new Error("B66_NO_TESTS");
    for (const name of names) {
      console.log("B66_TEST_FILE=" + name);
      invoke([path.join("tests", name)], sourceDir);
      tests++;
    }
  }
  console.log("B66_SOURCE_SYNTAX_CHECKED=" + scripts);
  console.log("B66_TEST_FILES_EXECUTED=" + tests);
  console.log("B66_TEST_RUNNER=PASS");
  return { scripts, tests };
}

if (require.main === module) {
  try {
    runSuite(process.argv[2] || "--all");
  } catch (error) {
    console.error("B66_TEST_RUNNER=FAIL: " + error.message);
    process.exitCode = 1;
  }
}

module.exports = Object.freeze({
  discoverSourceScripts,
  discoverTestFiles,
  runSuite
});
