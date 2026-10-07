"""Read-only certified PDF bundles behind the existing B66 assignment authority.

Private bytes reuse the existing workspace R2 binding. Callers must first resolve
the authenticated owner/workspace and read that owner's approved Saved Quote
Skill. No browser object key, upload, assignment or D1 mutation exists here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import stat
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from .b66_quote_assets import _read_r2_bytes
from .b66_saved_quote_skill_store import SavedQuoteSkillStoreError, validate_row_id

BUNDLE_SCHEMA = "b66.certified-pdf-bundle.v1"
# The certified scope includes multiple large font members. Independent archive
# and expanded ceilings admit the complete package while bounding Worker memory.
MAX_BUNDLE_ZIP_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_EXPANDED_BYTES = 48 * 1024 * 1024
MAX_BUNDLE_MEMBER_BYTES = 20 * 1024 * 1024
MAX_BUNDLE_JSON_BYTES = 1024 * 1024
MAX_BUNDLE_MEMBERS = 32
MAX_BUNDLE_COMPRESSION_RATIO = 1000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FONT_PATH = re.compile(r"^fonts/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:ttf|ttc|otf)$")
_MANIFEST_KEYS = frozenset({
    "schema", "saved_skill_id", "skill_fingerprint", "profile_fingerprint",
    "renderer_contract", "engine_version", "renderer_sha256", "certification",
    "supported_scope", "baseline_render_model", "files",
})


class B66CertifiedQuoteBundleError(ValueError):
    def __init__(self, code: str = "certified_bundle_invalid") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class B66CertifiedQuoteBundle:
    template: dict[str, Any] = field(repr=False)
    baseline_render_model: dict[str, Any] = field(repr=False)
    base_pdf: bytes = field(repr=False)
    fonts: dict[str, bytes] = field(repr=False)
    manifest: dict[str, Any] = field(repr=False)


def _hash(value: object) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise B66CertifiedQuoteBundleError()
    return value


def bundle_object_key(*, saved_skill_id: str, skill_fingerprint: str) -> str:
    try:
        row_id = validate_row_id(saved_skill_id)
    except SavedQuoteSkillStoreError as exc:
        raise B66CertifiedQuoteBundleError() from exc
    return f"b66/certified-quote-bundles/{row_id}/{_hash(skill_fingerprint)}/bundle.zip"


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise B66CertifiedQuoteBundleError()
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise B66CertifiedQuoteBundleError()


def _json_object(body: bytes) -> dict[str, Any]:
    if not body or len(body) > MAX_BUNDLE_JSON_BYTES:
        raise B66CertifiedQuoteBundleError()
    try:
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
            parse_constant=_invalid_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise B66CertifiedQuoteBundleError() from exc
    if not isinstance(value, dict):
        raise B66CertifiedQuoteBundleError()
    return value


def _allowed_member(name: object) -> bool:
    return isinstance(name, str) and (
        name in {"manifest.json", "template.json", "base.pdf"}
        or _FONT_PATH.fullmatch(name) is not None
    )


def _archive_members(archive: ZipFile) -> dict[str, Any]:
    infos = archive.infolist()
    if not 3 <= len(infos) <= MAX_BUNDLE_MEMBERS:
        raise B66CertifiedQuoteBundleError()
    result = {}
    total = 0
    for info in infos:
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (
            not _allowed_member(info.filename)
            or info.orig_filename != info.filename
            or info.filename in result
            or info.is_dir()
            or kind not in {0, stat.S_IFREG}
            or info.flag_bits & 1
            or info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
            or not 0 < info.file_size <= MAX_BUNDLE_MEMBER_BYTES
            or info.compress_size <= 0
            or info.file_size > info.compress_size * MAX_BUNDLE_COMPRESSION_RATIO
        ):
            raise B66CertifiedQuoteBundleError()
        total += info.file_size
        if total > MAX_BUNDLE_EXPANDED_BYTES:
            raise B66CertifiedQuoteBundleError()
        if info.filename.endswith(".json") and info.file_size > MAX_BUNDLE_JSON_BYTES:
            raise B66CertifiedQuoteBundleError()
        result[info.filename] = info
    if not {"manifest.json", "template.json", "base.pdf"} <= result.keys():
        raise B66CertifiedQuoteBundleError()
    return result


def _read_member(archive: ZipFile, info: Any) -> bytes:
    with archive.open(info) as member:
        body = member.read(info.file_size + 1)
    if len(body) != info.file_size:
        raise B66CertifiedQuoteBundleError()
    return body


def parse_bundle(
    body: bytes, *, saved_skill_id: str, skill_fingerprint: str,
    profile_fingerprint: str,
) -> B66CertifiedQuoteBundle:
    """Verify every private member before returning any renderable bytes."""
    bundle_object_key(saved_skill_id=saved_skill_id, skill_fingerprint=skill_fingerprint)
    _hash(profile_fingerprint)
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_BUNDLE_ZIP_BYTES:
        raise B66CertifiedQuoteBundleError()
    try:
        with ZipFile(BytesIO(body)) as archive:
            members = _archive_members(archive)
            manifest = _json_object(_read_member(archive, members["manifest.json"]))
            if (
                set(manifest) != _MANIFEST_KEYS
                or manifest.get("schema") != BUNDLE_SCHEMA
                or manifest.get("saved_skill_id") != saved_skill_id
                or manifest.get("skill_fingerprint") != skill_fingerprint
                or manifest.get("profile_fingerprint") != profile_fingerprint
                or not isinstance(manifest.get("certification"), dict)
                or manifest["certification"].get("status") != "PASS"
                or not isinstance(manifest.get("baseline_render_model"), dict)
                or not isinstance(manifest.get("supported_scope"), dict)
            ):
                raise B66CertifiedQuoteBundleError()
            # Imported lazily: ordinary B66/auth routes must remain available
            # without loading a native PDF engine.
            from . import b66_certified_pdf_renderer as renderer

            if (
                manifest.get("renderer_contract") != renderer.RENDERER_CONTRACT
                or manifest.get("engine_version") != renderer.ENGINE_VERSION
                or _hash(manifest.get("renderer_sha256")) != renderer.renderer_source_sha256()
            ):
                raise B66CertifiedQuoteBundleError("certified_bundle_renderer_mismatch")
            files = manifest.get("files")
            if not isinstance(files, dict) or set(files) != set(members) - {"manifest.json"}:
                raise B66CertifiedQuoteBundleError()
            payloads: dict[str, bytes] = {}
            for name, metadata in files.items():
                if (
                    not _allowed_member(name)
                    or not isinstance(metadata, dict)
                    or set(metadata) != {"sha256", "byte_length"}
                    or type(metadata.get("byte_length")) is not int
                    or metadata["byte_length"] != members[name].file_size
                ):
                    raise B66CertifiedQuoteBundleError()
                expected_hash = _hash(metadata.get("sha256"))
                payload = _read_member(archive, members[name])
                if hashlib.sha256(payload).hexdigest() != expected_hash:
                    raise B66CertifiedQuoteBundleError("certified_bundle_integrity_failed")
                payloads[name] = payload
            template = _json_object(payloads["template.json"])
            scope = template.get("supported_scope")
            if (
                not isinstance(scope, dict)
                or json.dumps(scope, sort_keys=True) != json.dumps(manifest["supported_scope"], sort_keys=True)
                or type(scope.get("max_item_rows")) is not int
                or not 1 <= scope["max_item_rows"] <= 100
            ):
                raise B66CertifiedQuoteBundleError()
            resources = template.get("resources")
            if not isinstance(resources, dict) or not isinstance(resources.get("fonts"), dict):
                raise B66CertifiedQuoteBundleError()
            font_paths: set[str] = set()
            for font in resources["fonts"].values():
                if not isinstance(font, dict) or not _FONT_PATH.fullmatch(str(font.get("file", ""))):
                    raise B66CertifiedQuoteBundleError()
                name = font["file"]
                if name not in files or _hash(font.get("sha256")) != files[name]["sha256"]:
                    raise B66CertifiedQuoteBundleError("certified_bundle_integrity_failed")
                font_paths.add(name)
            if set(files) != {"template.json", "base.pdf"} | font_paths:
                raise B66CertifiedQuoteBundleError()
            base = resources.get("base_document")
            if (
                not isinstance(base, dict)
                or _hash(base.get("sha256")) != files["base.pdf"]["sha256"]
                or not payloads["base.pdf"].startswith(b"%PDF-")
            ):
                raise B66CertifiedQuoteBundleError("certified_bundle_integrity_failed")
            baseline = manifest["baseline_render_model"]
            baseline_profile = baseline.get("template")
            if (
                not isinstance(baseline_profile, dict)
                or baseline_profile.get("fingerprint") != profile_fingerprint
                or baseline.get("derivedBy") != "quote-core"
                or not isinstance(baseline.get("coreTotals"), dict)
                or not isinstance(baseline.get("writtenWords"), str)
            ):
                raise B66CertifiedQuoteBundleError()
            return B66CertifiedQuoteBundle(
                template=template, baseline_render_model=baseline,
                base_pdf=payloads["base.pdf"],
                fonts={name: payloads[name] for name in font_paths}, manifest=manifest,
            )
    except B66CertifiedQuoteBundleError:
        raise
    except (BadZipFile, OSError, RuntimeError, ValueError, KeyError, TypeError, RecursionError) as exc:
        raise B66CertifiedQuoteBundleError() from exc


class B66CertifiedQuoteBundleStore:
    """Reads only the key derived from an existing approved assignment."""

    def __init__(self, r2_bucket: Any) -> None:
        if r2_bucket is None or not callable(getattr(r2_bucket, "get", None)):
            raise ValueError("private R2 binding is required")
        self.r2_bucket = r2_bucket

    async def get_bundle(
        self, *, saved_skill_id: str, skill_fingerprint: str,
        profile_fingerprint: str,
    ) -> B66CertifiedQuoteBundle | None:
        key = bundle_object_key(saved_skill_id=saved_skill_id, skill_fingerprint=skill_fingerprint)
        _hash(profile_fingerprint)
        try:
            obj = self.r2_bucket.get(key)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                return None
            declared_size = getattr(obj, "size", None)
            if declared_size is not None and (
                isinstance(declared_size, bool)
                or not isinstance(declared_size, (int, float))
                or not 0 < declared_size <= MAX_BUNDLE_ZIP_BYTES
            ):
                raise B66CertifiedQuoteBundleError()
            body = await _read_r2_bytes(obj)
            if declared_size is not None and len(body) != declared_size:
                raise B66CertifiedQuoteBundleError("certified_bundle_integrity_failed")
        except B66CertifiedQuoteBundleError:
            raise
        except Exception as exc:
            raise B66CertifiedQuoteBundleError("certified_bundle_read_failed") from exc
        return parse_bundle(
            body, saved_skill_id=saved_skill_id, skill_fingerprint=skill_fingerprint,
            profile_fingerprint=profile_fingerprint,
        )
