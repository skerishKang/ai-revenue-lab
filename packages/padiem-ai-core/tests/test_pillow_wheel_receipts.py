from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from padiem_ai_core.pillow_wheel_receipts import (
    APPROVED_PILLOW_WHEEL_RECEIPTS,
    LINUX_X64_RECEIPT,
    PILLOW_VERSION,
    WINDOWS_X64_RECEIPT,
    approved_receipt,
    PillowPlatform,
)


def test_exact_windows_and_linux_receipts_validate():
    assert PILLOW_VERSION == "12.3.0"
    assert WINDOWS_X64_RECEIPT.filename == "pillow-12.3.0-cp312-cp312-win_amd64.whl"
    assert WINDOWS_X64_RECEIPT.sha256 == "a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09"
    assert LINUX_X64_RECEIPT.filename == "pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    assert LINUX_X64_RECEIPT.sha256 == "78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91"
    assert set(APPROVED_PILLOW_WHEEL_RECEIPTS) == {"windows-x64", "linux-x64"}
    assert approved_receipt(PillowPlatform("Windows")) is WINDOWS_X64_RECEIPT
    assert approved_receipt(PillowPlatform("Linux")) is LINUX_X64_RECEIPT
    assert WINDOWS_X64_RECEIPT.attestation_verified is False
    assert WINDOWS_X64_RECEIPT.sbom_verified is False


def test_runtime_adoption_is_exact_and_ci_scoped():
    root = Path(__file__).parents[3]
    kagent = (root / "apps/korean-ai-code-agent/pyproject.toml").read_text(
        encoding="utf-8"
    )
    workflow = (root / ".github/workflows/validate-b54-kagent.yml").read_text(
        encoding="utf-8"
    )
    receipt_path = (
        root / "packages/padiem-ai-core/padiem_ai_core/pillow_wheel_receipts.py"
    )

    assert "Pillow" not in kagent
    assert "python -m padiem_ai_core.pillow_wheel_receipts" not in workflow
    assert (
        "python packages/padiem-ai-core/padiem_ai_core/pillow_wheel_receipts.py"
        in workflow
    )

    completed = subprocess.run(
        [sys.executable, str(receipt_path), "Linux"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "PILLOW_WHEEL_SHA256=" in completed.stdout
