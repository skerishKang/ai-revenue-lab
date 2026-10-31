"""#5895 — the Worker's cold init must touch no JS, and must not drag the PC lane in.

The deployed Python Worker runs `worker.py`, whose module import builds the app
(`app.main` calls `create_app()` at import). On this Worker's compat date
(2026-08-25 / Pyodide 3.13) the platform still carries its cold-init `NoGilError`
race, and a heavier cold init is what turns it into a 500 on every login and session
request — the incident this file pins.

Two contracts are proved here, both about **import time only**:

* no module reaches `js` or `pyodide` while the app is being imported. Every runtime
  access in this codebase is inside a function that runs for a request (for example
  ``connector_worker_webcrypto_verify._native_runtime``), and a top-level import would
  be the thing that breaks the Worker before a request can even be served;
* the PC lane modules (``chat_pc_drive`` and the mesh return leg) stay out of the
  factory's import graph. Every other consumer imports them inside the function that
  needs them, and the routes must do the same.

The check runs in a subprocess on purpose: the tripwire replaces ``js``/``pyodide`` in
``sys.modules``, which must not leak into the rest of this test session.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]

#: Import the app exactly the way the Worker entry does, with `js` and `pyodide`
#: replaced by tripwires that fail on any attribute access at all.
_PROBE = r"""
import sys
import types


class Tripwire(types.ModuleType):
    # Dunder probes (__path__, __spec__) are how the import machinery inspects every
    # module, so they answer normally; anything else (js.crypto, pyodide.ffi.to_js)
    # means the app reached into the runtime while importing.
    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise AssertionError("JS touched during import: " + self.__name__ + "." + name)


for module_name in ("js", "pyodide", "pyodide.ffi"):
    sys.modules[module_name] = Tripwire(module_name)

import app.app_factory  # noqa: E402,F401

# The factory's own import graph is what a request-time route mount adds to cold init.
leaked = [
    name for name in ("app.chat_pc_drive", "app.oracle_mesh_read_return_routes")
    if name in sys.modules
]
if leaked:
    raise AssertionError("PC lane imported at app-factory import time: " + ", ".join(leaked))

import app.main  # noqa: E402,F401  (the Worker's own entry import)

print("IMPORT_TIME_CLEAN")
"""


def test_importing_the_chat_app_never_touches_js_or_pyodide():
    completed = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-2000:]
    assert "IMPORT_TIME_CLEAN" in completed.stdout
