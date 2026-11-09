"""#6838: draft a validated B14 overlay from copied base rows plus reasoning blocks.

The tool must copy a base row whole, attach only the requested block, and refuse
anything the boot validator would refuse. Every identifier below is synthetic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from _registry_values import credential_binding_slot

APP_ROOT = Path(__file__).resolve().parents[1]
TOOL = APP_ROOT / "tools" / "b14_overlay_draft.py"
MODEL_ID = "vendor-a/chat-1"

BASE_REGISTRY = {
    "schema_version": 1,
    "comment": "synthetic base for overlay draft tests",
    "providers": {
        "vendor-a": {
            "base_origin": "https://api.vendor-a.example",
            "allowed_hosts": ["api.vendor-a.example"],
            "credential_source": "platform_secret",
            "credential_binding_name": credential_binding_slot(5),
            "enabled": True,
        },
    },
    "models": [
        {
            "id": MODEL_ID,
            "provider_id": "vendor-a",
            "upstream_model": "chat-1",
            "display_name": "Vendor A Chat 1",
            "provider_name": "Vendor A",
            "capabilities": ["chat"],
            "context_window": 8192,
            "input_price_usd_per_1m": 1.0,
            "output_price_usd_per_1m": 2.0,
            "source": "https://vendor-a.example/pricing",
            "source_checked_at": "2026-11-06",
            "enabled": True,
        },
    ],
    "groups": {"plus": [], "pro": [], "max": []},
}


def _run(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *(str(arg) for arg in args)],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.fixture()
def base(tmp_path: Path) -> Path:
    path = tmp_path / "base.json"
    path.write_text(json.dumps(BASE_REGISTRY), encoding="utf-8")
    return path


@pytest.fixture()
def reasoning() -> dict:
    return {"supported": True, "values": ["low", "high"], "thought_summary": True}


def test_generates_a_validated_overlay_from_the_base_row(
    tmp_path: Path, base: Path, reasoning: dict,
) -> None:
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"models": {MODEL_ID: reasoning}}), encoding="utf-8")
    out = tmp_path / "overlay.json"

    result = _run("--base", base, "--draft", draft, "--out", out)

    assert result.returncode == 0, result.stderr
    overlay = json.loads(out.read_text(encoding="utf-8"))
    assert overlay["schema_version"] == 1
    assert len(overlay["models"]) == 1
    row = overlay["models"][0]
    assert row["reasoning"] == reasoning
    assert {key: value for key, value in row.items() if key != "reasoning"} == (
        BASE_REGISTRY["models"][0]
    )

    check = _run("--base", base, "--check", out)
    assert check.returncode == 0, check.stderr
    assert check.stdout.startswith("OK:")


def test_rejects_an_unknown_reasoning_value(
    tmp_path: Path, base: Path,
) -> None:
    draft = tmp_path / "draft.json"
    draft.write_text(
        json.dumps({"models": {MODEL_ID: {"supported": True, "values": ["deepest"]}}}),
        encoding="utf-8",
    )
    out = tmp_path / "overlay.json"

    result = _run("--base", base, "--draft", draft, "--out", out)

    assert result.returncode == 1
    assert MODEL_ID in result.stderr
    assert "values" in result.stderr
    assert not out.exists()


def test_check_rejects_a_partial_model_row(
    tmp_path: Path, base: Path, reasoning: dict,
) -> None:
    overlay = tmp_path / "overlay.json"
    overlay.write_text(
        json.dumps({
            "schema_version": 1,
            "models": [{"id": MODEL_ID, "reasoning": reasoning}],
        }),
        encoding="utf-8",
    )

    result = _run("--base", base, "--check", overlay)

    assert result.returncode == 1
    assert MODEL_ID in result.stderr
    assert "missing keys" in result.stderr
