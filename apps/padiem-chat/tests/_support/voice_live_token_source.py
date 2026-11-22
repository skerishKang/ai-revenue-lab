"""Read the cross-product STT Worker sources for the #4643 live-token
contracts (#8060).

The STT Worker is a separate product directory (``padiem-voice-stt``), so
these cross-product reads live in a file-specific helper instead of the
shared ``claw_static``. Byte-faithful: the lockdown asserts pin the worker's
route, capability and key-binding names.
"""
from __future__ import annotations

from pathlib import Path

_APPS = Path(__file__).resolve().parents[3]


def worker_source() -> str:
    return (_APPS / "padiem-voice-stt" / "worker.py").read_text(encoding="utf-8")


def contract_source() -> str:
    return (_APPS / "padiem-voice-stt" / "voice_stt_contract.py").read_text(encoding="utf-8")
