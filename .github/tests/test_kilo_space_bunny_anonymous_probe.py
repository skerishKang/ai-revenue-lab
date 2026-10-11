"""Rewrite test_kilo_space_bunny_anonymous_probe.py: execution proofs -> retirement.

The probe was the only path that could POST to the retired Space Bunny lane.
It is now fail-closed, so these tests pin the retirement block.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "kilo_space_bunny_anonymous_probe.py"

spec = importlib.util.spec_from_file_location("kilo_space_bunny_anonymous_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_default_invocation_cannot_reach_network() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.main([])
    assert rc == 1
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in out.getvalue()


@pytest.mark.parametrize("modality", ["", "video", "IMAGE", "auto"])
def test_unknown_modality_fails_before_network(modality: str) -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.main(["--authorized-live-run", f"--modality={modality}"])
    assert rc == 1
    assert "KILO_POST_COUNT=0" in out.getvalue()


@pytest.mark.parametrize("modality", ["text", "image"])
def test_authorized_live_run_fails_closed_for_retired_lane(modality: str) -> None:
    # Owner final retirement decision (2026-10-07): even an authorized-live
    # invocation must not POST for the retired lane.
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.main(["--authorized-live-run", f"--modality={modality}"])
    assert rc == 1
    output = out.getvalue()
    assert "FAIL_RETIRED_LANE" in output
    assert "KILO_POST_COUNT=0" in output
    assert "RETIRED_LANE_EXECUTION=BLOCKED" in output


def test_run_never_touches_the_transport() -> None:
    calls = []

    def transport(body, headers):
        calls.append((body, headers))
        return 200, b'{"model":"stealth/space-bunny-alpha","choices":[{"message":{"content":"OK"}}]}'

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run("text", transport=transport)
    assert rc == 1
    assert calls == []
    assert "KILO_POST_COUNT=0" in out.getvalue()


def test_headers_are_always_anonymous_even_if_secret_env_exists(monkeypatch) -> None:
    monkeypatch.setenv("KILO_API_KEY", "secret-value")
    monkeypatch.setenv("PADIEM_KILO_API_KEY", "secret-value-2")
    headers = probe.canonical_headers()
    assert all(key.lower() != "authorization" for key in headers)
    assert "secret-value" not in repr(headers)


def test_historical_constants_are_preserved_for_audit() -> None:
    # Historical identity metadata survives even though the lane is retired.
    assert probe.UPSTREAM_MODEL == "stealth/space-bunny-alpha"
    assert probe.TEXT_MAX_TOKENS == 32
    assert probe.IMAGE_MAX_TOKENS == 1024
    assert probe.KILO_CHAT_URL == "https://api.kilo.ai/api/gateway/chat/completions"