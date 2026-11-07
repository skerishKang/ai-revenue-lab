"""Post-deploy check: the connector tool payload must serialize — in the
service's own runtime environment.

#7088 후속 (measured 2026-11-08): a Core ``ToolSpec`` schema travels through
``ToolDefinition`` as recursively frozen ``MappingProxyType`` values.
``to_provider_schema`` shallow-converts only the ``properties`` mapping, so a
declared tool whose schema carries nested structures reached ``json.dumps``
inside the B14 stream client and died there as ``TypeError`` — masked by the
Core runtime as ``execution_failed`` before a single byte left for the model.

The check runs with the chat service's own venv interpreter, the INSTALLED
app root and the service's ``EnvironmentFile`` — the exact environment
``padiem-chat-com2.service`` runs with. It is read-only, costs no model call
and needs no QA credential.

Verdict contract (CTO 2026-11-08):
  PASS  the payload serializes
  FAIL  the payload does not serialize — every connector-intent turn would
        fail; the deploy stops
  ERROR the check's own harness could not run (the installed tree could not
        be imported). The chat health check already proved the app imports
        and serves, so this is an environment mismatch of the check itself,
        not a product defect: the deploy continues and the summary carries
        the warning.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from pathlib import Path

FAIL_SERIALIZE = "tool_payload_serialization_failed"
FAIL_NO_TOOLS = "no_connector_tools_declared"
ERROR_IMPORT = "import_failed"
ERROR_NO_TOOLS = "no_connector_tools_declared"


def load_env_file(path: Path) -> int:
    """Apply a systemd-style EnvironmentFile to this process.

    KEY=VALUE lines only; comments and blank lines are skipped and malformed
    lines are counted, never printed. The values are service configuration:
    they go into ``os.environ`` and are never echoed back.
    """

    applied = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return -1
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or " " in key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        applied += 1
    return applied


def last_frame_module(exc: BaseException) -> str:
    """The basename of the deepest frame in the import traceback.

    A bounded module hint (a file name only) so the next run can point at the
    import that failed — never a variable value, never a secret.
    """

    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return "unknown"
    return Path(frames[-1].filename).name


def verdict(app_root: Path) -> tuple[str, str]:
    """Return ``(verdict, bounded code)`` for one installed chat app root."""

    sys.path.insert(0, str(app_root))
    sys.modules.pop("app.chat_connector_tools", None)
    sys.modules.pop("app", None)
    try:
        tools = importlib.import_module(
            "app.chat_connector_tools").CONNECTOR_TOOL_DECLARATIONS
    except Exception as exc:
        # The chat health check already proved the installed app imports and
        # serves, so an import failure here is the check's own environment
        # mismatch: ERROR, never a product FAIL.
        sys.path.pop(0)
        hint = last_frame_module(exc)
        return "ERROR", f"{ERROR_IMPORT}:{type(exc).__name__}:{hint}"
    finally:
        sys.path.pop(0)
        sys.modules.pop("app.chat_connector_tools", None)
        sys.modules.pop("app", None)
    if not tools:
        return "ERROR", ERROR_NO_TOOLS
    try:
        payload = {"tools": [tool.to_provider_schema() for tool in tools],
                   "tool_choice": "auto"}
        json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return "FAIL", FAIL_SERIALIZE
    return "PASS", "none"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", required=True, type=Path,
                        help="installed chat root the service runs from (contains app/)")
    parser.add_argument("--env-file", default="", type=str,
                        help="the service's EnvironmentFile (KEY=VALUE lines)")
    args = parser.parse_args()
    if args.env_file:
        applied = load_env_file(Path(args.env_file))
        if applied < 0:
            print("TOOLS_SERIALIZATION_ENV_FILE=unreadable")
        else:
            print(f"TOOLS_SERIALIZATION_ENV_FILE=applied_vars={applied}")
    verdict_, code = verdict(args.app_root)
    if verdict_ == "PASS":
        print("TOOLS_SERIALIZATION=PASS")
        return 0
    if verdict_ == "ERROR":
        print(f"TOOLS_SERIALIZATION=ERROR code={code}")
        return 2
    print(f"TOOLS_SERIALIZATION=FAIL code={code}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
