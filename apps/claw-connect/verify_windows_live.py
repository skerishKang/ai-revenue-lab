"""Non-destructive Windows source verification for PADIEM Claw Connect.

Safe by default on an occupied workstation. Every subprocess receives a unique
scratch state directory and test-owned HKCU keys. Does not start or stop a tray,
install/uninstall shortcuts, contact a Broker or touch the real product Run key.

Run: python apps/claw-connect/verify_windows_live.py

This proves local fail-closed bootstrap only, NOT signed WSS/DPAPI live E2E.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "claw_connect", *args],
        cwd=APP_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )


def _payload(proc: subprocess.CompletedProcess[str]) -> dict:
    try:
        value = json.loads(proc.stdout)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _read_run_entry(key: str) -> str | None:
    import winreg  # noqa: PLC0415

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "PadiemClawConnect")
        return value
    except FileNotFoundError:
        return None


def _delete_owned_scratch(root: str) -> None:
    """Clean ONLY a unique scratch root, never the real product profile."""
    import winreg  # noqa: PLC0415

    prefix = "Software\\PadiemClawConnectSelftest\\CentralLive"
    if not root.startswith(prefix):
        raise RuntimeError("scratch ownership check failed")
    for key in (root + "\\Run", root + "\\Pref", root):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def _verify_installer_contract() -> bool:
    """Static review only; actual install/uninstall requires isolated E2E."""
    code = (APP_ROOT / "install.ps1").read_text(encoding="utf-8")
    return (
        "& $PythonExePath -m padiem_connector autostart on" in code
        and "& $PythonExePath -m padiem_connector autostart off" in code
        and "Set-ItemProperty -Path $RunKey" not in code
        and "Remove-ItemProperty -Path $RunKey" not in code
    )


def main() -> int:
    if sys.platform != "win32":
        print(json.dumps({"ok": False, "reason": "windows_required"}))
        return 2

    checks: dict[str, bool] = {}
    # A UUID prevents collision with other LOCAL2 / CI workers on this HKCU.
    root = "Software\\PadiemClawConnectSelftest\\CentralLive" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="padiem-connect-verify-") as tmp:
        state = Path(tmp) / "state"
        env = {
            **os.environ,
            "CLAW_CONNECT_STATE_DIR": str(state),
            "CLAW_CONNECT_AUTOSTART_RUN_KEY": root + "\\Run",
            "CLAW_CONNECT_AUTOSTART_PREF_KEY": root + "\\Pref",
        }
        try:
            first = _run(env, "status")
            second = _run(env, "status")
            p1, p2 = _payload(first), _payload(second)
            enrollment1 = p1.get("enrollment") or {}
            enrollment2 = p2.get("enrollment") or {}
            checks["fresh_unregistered"] = (
                first.returncode == second.returncode == 0
                and p1.get("state") == p2.get("state") == "unregistered"
                and enrollment1.get("enrolled") is False
                and enrollment1.get("broker_endpoint_configured") is False
            )
            checks["identity_stable"] = (
                bool(enrollment1.get("device_id"))
                and enrollment1.get("device_id") == enrollment2.get("device_id")
            )

            rejected = _run(env, "autostart", "on")
            refused = _payload(rejected)
            checks["unenrolled_on_refused_without_registry_write"] = (
                rejected.returncode == 1
                and refused.get("ok") is False
                and _read_run_entry(root + "\\Run") is None
            )
            off = _run(env, "autostart", "off")
            show = _run(env, "autostart", "show")
            checks["opt_out_durable"] = (
                off.returncode == show.returncode == 0
                and _payload(show).get("preference") == "off"
                and _read_run_entry(root + "\\Run") is None
            )
            # A rejected opt-in must not reverse a pre-existing owner opt-out.
            refused_again = _run(env, "autostart", "on")
            checks["opt_out_survives_refused_on"] = (
                refused_again.returncode == 1
                and _payload(_run(env, "autostart", "show")).get("preference") == "off"
            )

            code = "0123456789abcdef0123456789abcdef"
            challenge = "chal-synthetic-20261013"
            attempt = _run(env, "enroll", challenge, code)
            after = _payload(_run(env, "status"))
            checks["unconfigured_enrollment_fails_closed"] = (
                attempt.returncode == 1
                and _payload(attempt).get("blocked") is True
                and after.get("state") == "unregistered"
            )
            raw = (state / "enrollment.json").read_text(encoding="utf-8")
            checks["no_pairing_secret_saved"] = (
                code not in raw and challenge not in raw
                and "credential_b64" not in raw
            )
            checks["installer_has_shared_autostart_gate"] = _verify_installer_contract()
        finally:
            _delete_owned_scratch(root)

    result = {"ok": all(checks.values()), "scope": "scratch_only_no_live_broker", "checks": checks}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
