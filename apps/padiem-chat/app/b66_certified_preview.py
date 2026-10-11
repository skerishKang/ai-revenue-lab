"""Read-only certified CGI preview base.

The bitmap is derived once from the certified CGI reference PDF with all
customer/mutable quotation fields removed. It is private R2 data and is served
only after the existing authenticated Saved Quote Skill authority is verified.
"""

from __future__ import annotations

import hashlib
import inspect
import re
from typing import Any

from .b66_quote_assets import _read_r2_bytes

MAX_PREVIEW_BYTES = 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

CGI_SKILL_FINGERPRINT = "b2f704fb88eb68aa7e3a2036257595411b211f18a08bcde35b225aa2f1596996"
CGI_PROFILE_FINGERPRINT = "ea4d4cce44472daab9eed90e321389456741eaecb85194e9db6a7dd61cc96935"
CGI_PREVIEW_SHA256 = "462f66f6e32a7409edafef09fed5a10fd99549738df38180d430c04ef99d0de9"
CGI_PREVIEW_OBJECT_KEY = (
    "b66/certified-preview-bases/"
    + CGI_SKILL_FINGERPRINT
    + "/"
    + CGI_PROFILE_FINGERPRINT
    + "/base.png"
)


class B66CertifiedPreviewError(RuntimeError):
    pass


class B66CertifiedPreviewStore:
    def __init__(self, r2_bucket: Any) -> None:
        if r2_bucket is None or not callable(getattr(r2_bucket, "get", None)):
            raise ValueError("private R2 binding is required")
        self.r2_bucket = r2_bucket

    async def get_preview(
        self, *, skill_fingerprint: str, profile_fingerprint: str
    ) -> bytes | None:
        if (
            skill_fingerprint != CGI_SKILL_FINGERPRINT
            or profile_fingerprint != CGI_PROFILE_FINGERPRINT
        ):
            return None
        if not _SHA256.fullmatch(skill_fingerprint) or not _SHA256.fullmatch(profile_fingerprint):
            return None
        try:
            obj = self.r2_bucket.get(CGI_PREVIEW_OBJECT_KEY)
            if inspect.isawaitable(obj):
                obj = await obj
            if obj is None:
                return None
            declared = getattr(obj, "size", None)
            if declared is not None and (
                isinstance(declared, bool)
                or not isinstance(declared, (int, float))
                or not 0 < declared <= MAX_PREVIEW_BYTES
            ):
                raise B66CertifiedPreviewError("certified_preview_invalid")
            body = await _read_r2_bytes(obj)
        except B66CertifiedPreviewError:
            raise
        except Exception as exc:
            raise B66CertifiedPreviewError("certified_preview_read_failed") from exc

        if (
            not isinstance(body, bytes)
            or not body.startswith(PNG_MAGIC)
            or not 0 < len(body) <= MAX_PREVIEW_BYTES
            or hashlib.sha256(body).hexdigest() != CGI_PREVIEW_SHA256
        ):
            raise B66CertifiedPreviewError("certified_preview_integrity_failed")
        if declared is not None and len(body) != declared:
            raise B66CertifiedPreviewError("certified_preview_integrity_failed")
        return body
