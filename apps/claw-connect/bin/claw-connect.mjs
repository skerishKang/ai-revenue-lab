#!/usr/bin/env node
/**
 * `npx @padiem/claw-connect` entry point (#4139 S1).
 *
 * Claw Connect is a Python program; this wrapper only locates a usable Python
 * interpreter on the user's PC and forwards every argument to
 * `python -m claw_connect`. It adds no server, no runner and no authority of
 * its own — the .exe installer path and this npx path execute the same module
 * with the same device id, protocol and permission model.
 */

import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgRoot = path.resolve(here, "..");
const pythonSourceRoot = pkgRoot; // the `claw_connect` package sits at pkgRoot

/** Candidate interpreters, in priority order. `py` is the Windows launcher. */
function candidates() {
  const list = [];
  if (process.env.PADIEM_PYTHON) list.push(process.env.PADIEM_PYTHON);
  list.push({ command: "py", args: ["-3"] });
  list.push({ command: "python3", args: [] });
  list.push({ command: "python", args: [] });
  return list;
}

function buildInvocation(candidate) {
  const command = typeof candidate === "string" ? candidate : candidate.command;
  const prefix = typeof candidate === "string" ? [] : candidate.args;
  return {
    command,
    args: [...prefix, "-c", ...[importShim(pythonSourceRoot)], "claw_connect", ...process.argv.slice(2)],
  };
}

/**
 * `-c` bootstrap that inserts the bundled source root and runs the module, so
 * the npx path and the installed .exe path both execute the same module.
 */
function importShim(root) {
  const rootLiteral = JSON.stringify(root);
  return [
    "import runpy, sys;",
    `sys.path.insert(0, ${rootLiteral});`,
    "sys.argv = sys.argv[1:];",
    "runpy.run_module('claw_connect', run_name='__main__')",
  ].join(" ");
}

function trySpawn(invocation) {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(invocation.command, invocation.args, {
        stdio: "inherit",
        windowsHide: true,
      });
    } catch {
      resolve(null);
      return;
    }
    child.on("error", () => resolve(null));
    child.on("exit", (code, signal) => {
      resolve(signal ? 1 : (code ?? 0));
    });
  });
}

async function main() {
  for (const candidate of candidates()) {
    const invocation = buildInvocation(candidate);
    const code = await trySpawn(invocation);
    if (code !== null) {
      process.exit(code);
    }
  }
  console.error(
    "Padiem Claw Connect: Python 3.11+ 를 찾지 못했습니다. " +
      "Python 설치 후 다시 시도하거나 PADIEM_PYTHON 환경변수를 지정하세요."
  );
  process.exit(69); // EX_UNAVAILABLE
}

main();
