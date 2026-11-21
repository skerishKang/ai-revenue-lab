"""Read a top-level numeric ``const NAME = value`` from a shipped JS file (#8060).

Extracts the declaration and evaluates only its value expression, so a browser
module with DOM side effects can still expose a contract constant. Keeps the raw
file read here so a contract test asserts on the parsed value, not source text.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "static"

_SCRIPT = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const name = process.argv[2];
const re = new RegExp("(?:^|\\n)\\s*(?:const|let|var)\\s+" + name + "\\s*=\\s*([^;\\n]+);");
const m = src.match(re);
if (!m) { process.stdout.write("null"); process.exit(0); }
let value;
try { value = Function("return (" + m[1] + ")")(); }
catch (e) { value = null; }
process.stdout.write(JSON.stringify(value === undefined ? null : value));
"""


def js_const(sheet: str, name: str):
    """Return the value of a top-level ``const`` in a static JS sheet."""
    node = subprocess.run(["node", "-e", _SCRIPT, str(_STATIC / sheet), name],
                          capture_output=True, text=True, timeout=30)
    if node.returncode != 0:
        raise AssertionError(f"node could not read {name} from {sheet}: {node.stderr[:400]}")
    return json.loads(node.stdout)


def sheet_text(name: str) -> str:
    """One shipped sheet as text; the read lives here, not in the test (#8060)."""
    return (_STATIC / name).read_text(encoding="utf-8")
