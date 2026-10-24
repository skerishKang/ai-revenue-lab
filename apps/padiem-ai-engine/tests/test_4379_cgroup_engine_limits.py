"""#4379 C-group 3rd slice: the Engine model request body total.

C7: the model routes carry no PADIEM request body total. The non-model Engine
route guards stay exactly where they were.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_engine_model_route_declares_no_padiem_body_total() -> None:
    from app.service import (
        MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES,
        MAX_REQUEST_BODY_BYTES,
    )

    assert MAX_MODEL_EXECUTE_REQUEST_BODY_BYTES is None
    # The non-model Engine guard stays a bounded guard: releasing the model path
    # is not a licence to release the tool, control, memory and approval routes.
    # #5573 raised its value 128 KiB -> 1 MiB by Owner decision; it is not removed.
    assert MAX_REQUEST_BODY_BYTES == 1024 * 1024  # Owner decision 2026-10-24 (#5573)


def test_the_engine_ingress_declares_no_padiem_body_total() -> None:
    ingress = (ROOT / "ingress" / "worker.mjs").read_text(encoding="utf-8")
    assert "const MAX_REQUEST_BODY_BYTES = null;" in ingress


def test_the_openapi_contract_publishes_no_model_body_total() -> None:
    import json

    contract = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    post = contract["paths"]["/internal/v1/execute"]["post"]
    assert post["x-engine-max-body-bytes"] is None
