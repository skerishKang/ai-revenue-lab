"""#3099: the canonical "already registered" answer must stay distinct.

The Broker refuses a second ACTIVE binding for the same device with
``duplicate_device_binding``. That is a definite answer, so the owner approval
route must pass the code through instead of collapsing it into the generic
``native_pc_registration_unconfirmed``, and the Claw page must recognise it so
the owner is told "already registered" rather than "did not complete".

These assertions pin both sides of that mapping. They deliberately do not
change any registration, credential or execution behaviour.
"""
from __future__ import annotations

from pathlib import Path

from app.connector_one_click_approval_route import _NATIVE_FAILURE_CODES

ROOT = Path(__file__).resolve().parents[1]
ALREADY_REGISTERED = "duplicate_device_binding"


def test_route_passes_the_canonical_already_registered_code():
    assert ALREADY_REGISTERED in _NATIVE_FAILURE_CODES
    # The generic fallback stays a literal, never an allowlisted pass-through.
    assert "native_pc_registration_unconfirmed" not in _NATIVE_FAILURE_CODES


def test_claw_page_recognises_and_words_the_already_registered_answer():
    script = (ROOT / "static" / "claw-home-choices.js").read_text(encoding="utf-8")
    # The code must be in the page's denial allowlist, so the exact stage is
    # recorded instead of "unclassified".
    assert f'"{ALREADY_REGISTERED}"' in script
    # The specific note must exist and must not be overwritten by the generic
    # failure note.
    assert "alreadyRegistered" in script
    assert "이미 등록된 기기입니다" in script
