"""Source-owned exact wheel receipts for the Pillow 12.3.0 runtime adoption.

This module is the *single* machine-readable authority for which Pillow
artifact PADIEM CI is allowed to install. It is deliberately a plain data
module with no Pillow import, no network access and no filesystem access, so it
can be read by the Core tests, by the KAgent facade tests, and by the CI step
that downloads and verifies the wheel.

Scope and non-equivalence
-------------------------
This is the #3037 *runtime receipt* contract. It does not replace or edit the
#3016 source-only provenance decision, the #2931 source behavior audit, the
##2990 reconciliation, or the canonical OSS intake matrix. Those documents stay
exactly as they were: #3016 recorded that platform-specific acceptance was
*required*, and this module is the artifact that satisfies that requirement for
two platforms only.

Nothing here is a general "PyPI is trusted" statement. A receipt authorizes one
exact filename, one exact digest, one exact size, one exact platform and ABI.
Any drift is a rejection, not a re-resolution.

Explicitly unverified
---------------------
The upstream Pillow 12.3.0 release publishes per-artifact provenance material,
but this audit did **not** fetch, parse and bind a release-specific PEP 740
attestation or a release-specific SBOM to either wheel below. Both receipts
therefore record that as unverified rather than implying verification.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Final

__all__ = [
    "PILLOW_LICENSE",
    "PILLOW_LICENSE_URL",
    "PILLOW_SDIST_SHA256",
    "PILLOW_SOURCE_RELEASE_REF",
    "PILLOW_UPSTREAM_COMMIT",
    "PILLOW_VERSION",
    "PillowWheelReceipt",
    "PillowWheelReceiptError",
    "APPROVED_PILLOW_WHEEL_RECEIPTS",
    "PillowPlatform",
    "approved_receipt",
    "approved_receipts",
    "main",
    "sha256_of_bytes",
    "shell_export",
    "verify_wheel_file",
]


PILLOW_VERSION: Final = "12.3.0"

#: Lightweight upstream tag object, which for Pillow is the release commit.
PILLOW_UPSTREAM_COMMIT: Final = "bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d"
PILLOW_SOURCE_RELEASE_REF: Final = (
    "https://github.com/python-pillow/Pillow/releases/tag/12.3.0"
)

#: Single source distribution for the same release, recorded so the wheel
#: receipts can be cross-referenced against one source identity.
PILLOW_SDIST_SHA256: Final = "3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce"

#: SPDX-style identifier used by the canonical OSS intake matrix, plus the exact
#: upstream LICENSE file that grants it.
PILLOW_LICENSE: Final = "MIT-CMU"
PILLOW_LICENSE_URL: Final = (
    "https://github.com/python-pillow/Pillow/blob/"
    f"{PILLOW_UPSTREAM_COMMIT}/LICENSE"
)

#: Native-extension posture, recorded per platform because the bundled
#: third-party codec binaries differ between the two builds.
_NATIVE_POSTURE = (
    "Wheel ships Pillow's compiled extensions (_imaging, _imagingft, "
    "_imagingcms, _webp, _avif, _imagingmath, _imagingmorph) linked against "
    "bundled third-party codec/image libraries (zlib, libjpeg, libtiff, "
    "FreeType, LittleCMS, libwebp, OpenJPEG and libavif). Libraries are linked "
    "at build time; optional platform paths (FriBiDi, Tk, platform User32) "
    "remain dynamic. Core image helpers decode only PNG/JPEG/WEBP/GIF and "
    "never call Image.show, ImageGrab, an external helper, EPS/Ghostscript or "
    "a network or provider API."
)

#: Same fact, recorded as an explicit negative so a reader cannot mistake the
#: absence of a verification for a verification.
_ATTESTATION_NOT_VERIFIED = (
    "Release-specific PEP 740 attestation was NOT verified by this audit; the "
    "receipt is accepted on the official PyPI origin plus the exact recorded "
    "digest only."
)
_SBOM_NOT_VERIFIED = (
    "Release-specific SBOM was NOT verified by this audit; upstream is "
    "recorded as embedding one, but no SBOM was fetched or bound to either "
    "wheel below."
)

_SHA256_RE: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_COMMIT_RE: Final = re.compile(r"\A[0-9a-f]{40}\Z")
_WHEEL_RE: Final = re.compile(
    r"\Apillow-(?P<version>\d+\.\d+\.\d+)"
    r"-(?P<python>[^-]+)-(?P<abi>[^-]+)-(?P<platform>.+)\.whl\Z"
)
_ORIGIN: Final = "https://files.pythonhosted.org"

#: The two platforms KAgent CI actually runs. Nothing else is approved.
_LINUX_X64_TAG: Final = "manylinux_2_27_x86_64.manylinux_2_28_x86_64"


class PillowWheelReceiptError(ValueError):
    """A receipt is missing, malformed, or does not match the artifact."""


@dataclass(frozen=True, slots=True)
class PillowPlatform:
    """A CI runner identity, matched against an approved platform tag."""

    system: str

    def __post_init__(self) -> None:
        if self.system not in {"Linux", "Windows"}:
            raise PillowWheelReceiptError(
                "no approved Pillow wheel receipt for this platform"
            )


@dataclass(frozen=True, slots=True)
class PillowWheelReceipt:
    """One exact, source-owned wheel authorization.

    A receipt is a flat, immutable description of a single file. Two receipts
    never share a filename, and a receipt never authorizes "whatever pip
    resolves".
    """

    platform_key: str
    filename: str
    python_tag: str
    abi_tag: str
    platform_tag: str
    sha256: str
    size_bytes: int
    url: str
    upload_time: str
    yanked: bool
    requires_python: str
    license_id: str
    license_url: str
    source_release_ref: str
    source_release_commit: str
    native_library_posture: str
    attestation_verified: bool
    sbom_verified: bool
    attestation_note: str
    sbom_note: str

    def __post_init__(self) -> None:
        if not self.filename.endswith(".whl"):
            raise PillowWheelReceiptError("receipt must identify a .whl file")

        match = _WHEEL_RE.match(self.filename)
        if match is None:
            raise PillowWheelReceiptError("receipt filename is not a valid wheel name")
        if match.group("version") != PILLOW_VERSION:
            raise PillowWheelReceiptError(
                f"receipt filename must be Pillow {PILLOW_VERSION}"
            )
        if match.group("python") != self.python_tag:
            raise PillowWheelReceiptError("filename python tag does not match receipt")
        if match.group("abi") != self.abi_tag:
            raise PillowWheelReceiptError("filename ABI tag does not match receipt")
        if match.group("platform") != self.platform_tag:
            raise PillowWheelReceiptError(
                "filename platform tag does not match receipt"
            )

        # CPython 3.12 is the only approved interpreter. A free-threaded or
        # PyPy artifact would carry a different ABI tag and is rejected here.
        if self.python_tag != "cp312" or self.abi_tag != "cp312":
            raise PillowWheelReceiptError("receipt must target CPython 3.12 (cp312)")

        if not _SHA256_RE.match(self.sha256):
            raise PillowWheelReceiptError("sha256 must be 64 lowercase hex digits")
        if self.size_bytes <= 0:
            raise PillowWheelReceiptError("size_bytes must be positive")
        if not self.url.startswith(f"{_ORIGIN}/packages/"):
            raise PillowWheelReceiptError(
                "receipt url must be an official files.pythonhosted.org artifact"
            )
        if not self.url.endswith(f"/{self.filename}"):
            raise PillowWheelReceiptError("receipt url must end with the filename")
        if self.yanked:
            raise PillowWheelReceiptError("a yanked artifact cannot be approved")
        if not self.upload_time:
            raise PillowWheelReceiptError("receipt must record the upload time")

        if not _COMMIT_RE.match(self.source_release_commit):
            raise PillowWheelReceiptError(
                "source release commit must be a 40-hex commit id"
            )
        if self.source_release_ref != PILLOW_SOURCE_RELEASE_REF:
            raise PillowWheelReceiptError("source release ref does not match the pin")
        if self.license_id != PILLOW_LICENSE:
            raise PillowWheelReceiptError("license must match the audited MIT-CMU")
        if self.license_url != PILLOW_LICENSE_URL:
            raise PillowWheelReceiptError(
                "license url must be the commit-pinned upstream LICENSE"
            )
        if not self.native_library_posture:
            raise PillowWheelReceiptError("native library posture must be recorded")

        # Both unverified facts are recorded as False plus an explicit sentence.
        # Removing either note would turn an unverified claim into an implied
        # verification, so they are part of the contract.
        if self.attestation_verified or self.sbom_verified:
            raise PillowWheelReceiptError(
                "this audit did not verify a release-specific attestation or SBOM"
            )
        if not self.attestation_note or not self.sbom_note:
            raise PillowWheelReceiptError(
                "unverified attestation/SBOM facts must be recorded explicitly"
            )

        if "manylinux" in self.platform_tag:
            if "x86_64" not in self.platform_tag:
                raise PillowWheelReceiptError(
                    "linux receipt must target x86_64"
                )
        elif self.platform_tag != "win_amd64":
            raise PillowWheelReceiptError("platform tag is not approved")

    def receipt_id(self) -> str:
        return f"{self.python_tag}/{self.platform_tag}"

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection. No host paths, no secrets."""

        return {
            "platform_key": self.platform_key,
            "receipt_id": self.receipt_id(),
            "package": "Pillow",
            "version": PILLOW_VERSION,
            "filename": self.filename,
            "python_tag": self.python_tag,
            "abi_tag": self.abi_tag,
            "platform_tag": self.platform_tag,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "url": self.url,
            "upload_time": self.upload_time,
            "yanked": self.yanked,
            "requires_python": self.requires_python,
            "license_id": self.license_id,
            "license_url": self.license_url,
            "source_release_ref": self.source_release_ref,
            "source_release_commit": self.source_release_commit,
            "native_library_posture": self.native_library_posture,
            "attestation_verified": self.attestation_verified,
            "sbom_verified": self.sbom_verified,
            "attestation_note": self.attestation_note,
            "sbom_note": self.sbom_note,
        }


WINDOWS_X64_RECEIPT: Final = PillowWheelReceipt(
    platform_key="windows-x64",
    filename="pillow-12.3.0-cp312-cp312-win_amd64.whl",
    python_tag="cp312",
    abi_tag="cp312",
    platform_tag="win_amd64",
    sha256="a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09",
    size_bytes=7_227_137,
    url=(
        "https://files.pythonhosted.org/packages/45/89/"
        "da2f7971a317f83d807fdd4065c0af40208e59e692cc43d315a71a0e96d1/"
        "pillow-12.3.0-cp312-cp312-win_amd64.whl"
    ),
    upload_time="2026-07-01T11:54:22.025716Z",
    yanked=False,
    requires_python=">=3.10",
    license_id=PILLOW_LICENSE,
    license_url=PILLOW_LICENSE_URL,
    source_release_ref=PILLOW_SOURCE_RELEASE_REF,
    source_release_commit=PILLOW_UPSTREAM_COMMIT,
    native_library_posture=_NATIVE_POSTURE,
    attestation_verified=False,
    sbom_verified=False,
    attestation_note=_ATTESTATION_NOT_VERIFIED,
    sbom_note=_SBOM_NOT_VERIFIED,
)

LINUX_X64_RECEIPT: Final = PillowWheelReceipt(
    platform_key="linux-x64",
    filename="pillow-12.3.0-cp312-cp312-"
    "manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
    python_tag="cp312",
    abi_tag="cp312",
    platform_tag=_LINUX_X64_TAG,
    sha256="78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91",
    size_bytes=6_940_830,
    url=(
        "https://files.pythonhosted.org/packages/84/21/"
        "a35af28dcc61f37ed850a2d64c65c701321dfbf25085e469d5559360cbbf/"
        "pillow-12.3.0-cp312-cp312-"
        "manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    ),
    upload_time="2026-07-01T11:54:13.732453Z",
    yanked=False,
    requires_python=">=3.10",
    license_id=PILLOW_LICENSE,
    license_url=PILLOW_LICENSE_URL,
    source_release_ref=PILLOW_SOURCE_RELEASE_REF,
    source_release_commit=PILLOW_UPSTREAM_COMMIT,
    native_library_posture=_NATIVE_POSTURE,
    attestation_verified=False,
    sbom_verified=False,
    attestation_note=_ATTESTATION_NOT_VERIFIED,
    sbom_note=_SBOM_NOT_VERIFIED,
)

#: The complete approved set. Two platforms, one artifact each.
APPROVED_PILLOW_WHEEL_RECEIPTS: Final[dict[str, PillowWheelReceipt]] = {
    WINDOWS_X64_RECEIPT.platform_key: WINDOWS_X64_RECEIPT,
    LINUX_X64_RECEIPT.platform_key: LINUX_X64_RECEIPT,
}


def approved_receipts() -> tuple[PillowWheelReceipt, ...]:
    """Every approved receipt, in a stable order."""

    return tuple(APPROVED_PILLOW_WHEEL_RECEIPTS[key] for key in sorted(APPROVED_PILLOW_WHEEL_RECEIPTS))


def approved_receipt(platform: PillowPlatform) -> PillowWheelReceipt:
    """Resolve the one receipt for ``platform``, or refuse.

    There is deliberately no fuzzy match and no platform fallback: an
    unreviewed runner must fail closed rather than receive a neighbouring
    platform's wheel.
    """

    key = {
        "Windows": WINDOWS_X64_RECEIPT.platform_key,
        "Linux": LINUX_X64_RECEIPT.platform_key,
    }[platform.system]
    return APPROVED_PILLOW_WHEEL_RECEIPTS[key]


def sha256_of_bytes(data: bytes) -> str:
    """Digest used by both the verifier and its tests."""

    return hashlib.sha256(data).hexdigest()


def verify_wheel_file(path: str, receipt: PillowWheelReceipt) -> None:
    """Verify a downloaded wheel against ``receipt`` before it is installed.

    Checks the filename, the exact byte size and the exact SHA-256, in that
    order, so a truncated or substituted download is rejected before any
    installer runs. Never installs and never executes the artifact.
    """

    from pathlib import Path

    wheel_path = Path(path)
    if wheel_path.name != receipt.filename:
        raise PillowWheelReceiptError(
            f"downloaded filename {wheel_path.name!r} does not match the "
            f"approved {receipt.filename!r}"
        )
    if not wheel_path.is_file():
        raise PillowWheelReceiptError(f"wheel not found: {receipt.filename}")

    size = wheel_path.stat().st_size
    if size != receipt.size_bytes:
        raise PillowWheelReceiptError(
            f"wheel size {size} does not match the approved "
            f"{receipt.size_bytes}"
        )

    digest = hashlib.sha256()
    with wheel_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != receipt.sha256:
        raise PillowWheelReceiptError(
            f"wheel sha256 {actual} does not match the approved {receipt.sha256}"
        )


def shell_export(platform: PillowPlatform) -> str:
    """Bash ``export`` lines for the approved artifact, for CI use.

    CI reads the filename, URL, size and digest from here instead of repeating
    them, so the workflow and the receipts cannot drift apart.
    """

    receipt = approved_receipt(platform)
    fields = {
        "PILLOW_WHEEL_FILENAME": receipt.filename,
        "PILLOW_WHEEL_URL": receipt.url,
        "PILLOW_WHEEL_SIZE": str(receipt.size_bytes),
        "PILLOW_WHEEL_SHA256": receipt.sha256,
        "PILLOW_WHEEL_PLATFORM_TAG": receipt.platform_tag,
        "PILLOW_WHEEL_PYTHON_TAG": receipt.python_tag,
        "PILLOW_WHEEL_ABI_TAG": receipt.abi_tag,
        "PILLOW_WHEEL_RECEIPT_ID": receipt.receipt_id(),
    }
    return "\n".join(
        f'export {name}="{value}"' for name, value in fields.items()
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m padiem_ai_core.pillow_wheel_receipts <Linux|Windows> [wheel]``.

    With one argument, prints the shell exports. With two, verifies the
    downloaded wheel against the receipt. A non-zero exit means CI must stop.
    """

    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: pillow_wheel_receipts <Linux|Windows> [wheel-path]", file=sys.stderr)
        return 2

    try:
        platform = PillowPlatform(system=args[0])
        if len(args) == 1:
            print(shell_export(platform))
            return 0
        if len(args) == 2:
            verify_wheel_file(args[1], approved_receipt(platform))
            return 0
    except PillowWheelReceiptError as exc:
        print(f"pillow wheel receipt rejected: {exc}", file=sys.stderr)
        return 1

    print("expected one or two arguments", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - exercised via CI
    raise SystemExit(main())
