from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

import bundle
import renderer

PATH = "/internal/v1/render"
MAX_REQUEST_BYTES = 32 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAVED_ID = re.compile(r"^b66skill_[0-9a-f]{32}$")


def _json_error(status: int, code: str) -> Response:
    return Response(
        json.dumps({"ok": False, "error": {"code": code}}, separators=(",", ":")),
        status=status,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if urlparse(str(request.url)).path != PATH:
            return _json_error(404, "not_found")
        if str(request.method).upper() != "POST":
            return _json_error(405, "method_not_allowed")
        content_type = request.headers.get("content-type") if request.headers is not None else None
        if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/json":
            return _json_error(415, "unsupported_media_type")
        declared = request.headers.get("content-length") if request.headers is not None else None
        if declared:
            try:
                if int(declared) > MAX_REQUEST_BYTES:
                    return _json_error(413, "request_too_large")
            except ValueError:
                return _json_error(400, "invalid_content_length")
        try:
            raw = await request.text()
            body = raw.encode("utf-8")
            if not body or len(body) > MAX_REQUEST_BYTES:
                return _json_error(413 if len(body) > MAX_REQUEST_BYTES else 400, "request_too_large" if len(body) > MAX_REQUEST_BYTES else "invalid_json")
            data = json.loads(raw)
        except Exception:
            return _json_error(400, "invalid_json")
        if not isinstance(data, dict) or set(data) != {"saved_skill_id", "skill_fingerprint", "profile_fingerprint", "render_model"}:
            return _json_error(400, "unsupported_field")
        saved = data["saved_skill_id"]
        skill_fp = data["skill_fingerprint"]
        profile_fp = data["profile_fingerprint"]
        model = data["render_model"]
        if (
            not isinstance(saved, str) or not _SAVED_ID.fullmatch(saved)
            or not isinstance(skill_fp, str) or not _SHA256.fullmatch(skill_fp)
            or not isinstance(profile_fp, str) or not _SHA256.fullmatch(profile_fp)
            or not isinstance(model, dict)
            or model.get("derivedBy") != "quote-core"
            or not isinstance(model.get("template"), dict)
            or model["template"].get("fingerprint") != profile_fp
        ):
            return _json_error(422, "invalid_render_request")
        try:
            private = await bundle.load_bundle(
                getattr(self.env, "PADIEM_WORKSPACE_FILES", None),
                saved_skill_id=saved,
                skill_fingerprint=skill_fp,
                profile_fingerprint=profile_fp,
            )
            pdf = renderer.render_pdf(
                template=private.template,
                baseline_render_model=private.baseline_render_model,
                render_model=model,
                base_pdf=private.base_pdf,
                fonts=private.fonts,
            )
        except renderer.B66CertifiedPdfError as exc:
            return _json_error(422 if exc.code.startswith("REJECT_") else 503, "render_input_rejected" if exc.code.startswith("REJECT_") else "render_unavailable")
        except bundle.BundleError:
            return _json_error(503, "bundle_unavailable")
        except Exception:
            return _json_error(503, "render_failed")
        if not isinstance(pdf, bytes) or not pdf.startswith(b"%PDF-") or len(pdf) > MAX_RESPONSE_BYTES:
            return _json_error(503, "render_failed")
        return Response(
            pdf,
            status=200,
            headers={
                "Content-Type": "application/pdf",
                "Cache-Control": "private, no-store, max-age=0",
                "X-Content-Type-Options": "nosniff",
            },
        )
