import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgRoot = path.resolve(here, "..");
const wrapper = path.join(pkgRoot, "bin", "claw-connect.mjs");

function runWrapper(args, env = {}) {
  return spawnSync(process.execPath, [wrapper, ...args], {
    encoding: "utf8",
    env: { ...process.env, ...env },
    timeout: 30_000,
  });
}

test("package manifest exposes the claw-connect bin", () => {
  const manifest = JSON.parse(readFileSync(path.join(pkgRoot, "package.json"), "utf8"));
  assert.equal(manifest.bin["claw-connect"], "bin/claw-connect.mjs");
  assert.ok(manifest.files.includes("claw_connect/"));
});

test("the wrapper prints the product version", () => {
  const result = runWrapper(["--version"]);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Padiem Claw Connect 0\.1\.0/);
});

test("the wrapper forwards to the same module the installer runs", () => {
  const result = runWrapper(["status"]);
  assert.equal(result.status, 0, result.stderr);
  const status = JSON.parse(result.stdout);
  assert.equal(status.product, "Padiem Claw Connect");
  assert.equal(status.state, "disconnected");
  assert.equal(status.resident_running, false);
  assert.equal(status.autostart_enabled, false);
});

test("a missing interpreter is reported instead of hanging", () => {
  const result = runWrapper(["status"], { PADIEM_PYTHON: "definitely-not-a-python-binary" });
  // The wrapper falls back to the system interpreter when the override is
  // wrong, so a successful status is also acceptable; only a hang is a bug.
  assert.ok(result.status === 0 || result.status === 69, `status=${result.status}`);
});

test("autostart on/off round trip through the wrapper", () => {
  const on = runWrapper(["autostart", "on"]);
  assert.equal(on.status, 0, on.stderr);
  const enabled = JSON.parse(on.stdout);
  assert.equal(enabled.ok, true);
  assert.equal(enabled.enabled, true);

  const off = runWrapper(["autostart", "off"]);
  assert.equal(off.status, 0, off.stderr);
  const disabled = JSON.parse(off.stdout);
  assert.equal(disabled.enabled, false);
});
