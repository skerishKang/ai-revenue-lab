import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import os from "node:os";
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

test("autostart on is fail-closed without a durable credential, off is allowed", () => {
  // The real HKCU stores are exercised here, but under a test-owned key root
  // and a scratch state directory: a test run must never leave a durable
  // autostart opt-out in the developer's own profile, and must not depend on
  // whether that profile happens to hold a real enrollment. On non-Windows
  // hosts the CLI uses the in-memory stores and these overrides are inert.
  const root = "Software\\PadiemClawConnectSelftest";
  const stateDir = path.join(os.tmpdir(), `claw-connect-autostart-test-${process.pid}`);
  const isolated = {
    CLAW_CONNECT_AUTOSTART_RUN_KEY: `${root}\\Run`,
    CLAW_CONNECT_AUTOSTART_PREF_KEY: `${root}\\Pref`,
    CLAW_CONNECT_STATE_DIR: stateDir,
  };

  try {
    // No committed record exists, so the owner CLI must refuse rather than
    // register. The old behaviour (register with no enrollment) was a bypass.
    const on = runWrapper(["autostart", "on"], isolated);
    assert.equal(on.status, 1, on.stderr);
    const refused = JSON.parse(on.stdout);
    assert.equal(refused.ok, false);
    assert.equal(refused.detail, "no durable, valid canonical credential for this PC");

    // off is always allowed, and records the durable owner choice.
    const off = runWrapper(["autostart", "off"], isolated);
    assert.equal(off.status, 0, off.stderr);
    const disabled = JSON.parse(off.stdout);
    assert.equal(disabled.enabled, false);

    // A fresh process still reads the owner's opt-out: the choice is durable,
    // not just an in-memory flag of the process that wrote it.
    const show = JSON.parse(runWrapper(["autostart", "show"], isolated).stdout);
    assert.equal(show.enabled, false);
    assert.equal(show.preference, "off");
  } finally {
    rmSync(stateDir, { recursive: true, force: true });
    if (process.platform === "win32") {
      for (const key of [`${root}\\Run`, `${root}\\Pref`, root]) {
        spawnSync("reg", ["delete", `HKCU\\${key}`, "/f"]);
      }
    }
  }
});
