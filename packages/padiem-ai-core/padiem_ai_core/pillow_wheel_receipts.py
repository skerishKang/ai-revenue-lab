"""Pinned official Pillow 12.3.0 wheel receipts for #3037 Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final

PILLOW_VERSION: Final = "12.3.0"
PILLOW_SOURCE_RELEASE_REF: Final = "https://github.com/python-pillow/Pillow/releases/tag/12.3.0"
PILLOW_LICENSE: Final = "MIT-CMU"

@dataclass(frozen=True, slots=True)
class PillowWheelReceipt:
    filename: str
    python_tag: str
    abi_tag: str
    platform_tag: str
    sha256: str
    size_bytes: int
    official_origin: str
    source_release_ref: str
    license_id: str
    native_library_posture: str

    def validate(self) -> None:
        if not self.filename.endswith(".whl"):
            raise ValueError("Pillow receipt must identify a wheel")
        if not (self.python_tag == "cp312" and self.abi_tag == "cp312"):
            raise ValueError("Pillow receipt must target CPython 3.12")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("Pillow receipt must contain a lowercase SHA-256")
        if self.official_origin != "https://files.pythonhosted.org":
            raise ValueError("Pillow receipt must use the official PyPI file origin")
        if self.source_release_ref != PILLOW_SOURCE_RELEASE_REF or self.license_id != PILLOW_LICENSE:
            raise ValueError("Pillow receipt provenance linkage is invalid")
        if "manylinux" in self.platform_tag:
            if "x86_64" not in self.platform_tag:
                raise ValueError("Linux Pillow receipt must target x86_64")
        elif self.platform_tag != "win_amd64":
            raise ValueError("Pillow receipt platform tag is unsupported")

WINDOWS_X64_RECEIPT: Final = PillowWheelReceipt(
    filename="pillow-12.3.0-cp312-cp312-win_amd64.whl",
    python_tag="cp312", abi_tag="cp312", platform_tag="win_amd64",
    sha256="a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09",
    size_bytes=7_227_137, official_origin="https://files.pythonhosted.org",
    source_release_ref=PILLOW_SOURCE_RELEASE_REF, license_id=PILLOW_LICENSE,
    native_library_posture="bundled native codec/image libraries; no EPS/Ghostscript or external helper execution",
)
LINUX_X64_RECEIPT: Final = PillowWheelReceipt(
    filename="pillow-12.3.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
    python_tag="cp312", abi_tag="cp312",
    platform_tag="manylinux_2_27_x86_64.manylinux_2_28_x86_64",
    sha256="78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91",
    size_bytes=6_940_830, official_origin="https://files.pythonhosted.org",
    source_release_ref=PILLOW_SOURCE_RELEASE_REF, license_id=PILLOW_LICENSE,
    native_library_posture="manylinux native image libraries; no EPS/Ghostscript or external helper execution",
)
PILLOW_WHEEL_RECEIPTS: Final = (WINDOWS_X64_RECEIPT, LINUX_X64_RECEIPT)

def validate_pillow_wheel_receipts() -> tuple[PillowWheelReceipt, ...]:
    for receipt in PILLOW_WHEEL_RECEIPTS:
        receipt.validate()
    if len({r.filename for r in PILLOW_WHEEL_RECEIPTS}) != 2:
        raise ValueError("Pillow receipts must cover two distinct platforms")
    return PILLOW_WHEEL_RECEIPTS

def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()
