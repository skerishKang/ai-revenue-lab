"""Engine result lookup and image projection."""
from __future__ import annotations

import json
import re
from typing import Any
from starlette.responses import JSONResponse
from .history import HistoryForbidden
from .oracle_mesh_http import _error, _response
from .oracle_mesh_pc_paths import _PC_FILES_SAFE_REF


async def _engine_pc_public_output(history_store: Any, *, payload: dict, uid: str,
                                   dispatch: dict, output: str, device_id: str | None = None,
                                   force: bool = False) -> tuple[dict | None, JSONResponse | None]:
    """Project verified command text; the full original stays outside model context."""
    if len(output) <= 4096 and not force:
        return {"output": output}, None
    store = getattr(history_store, "store_pc_output", None)
    if not callable(store):
        return None, _error(503, "pc_output_store_unavailable")
    try:
        if device_id is None:
            # Legacy drive status/result requests contain no device. Read the
            # pinned row's device, never guess the owner's current/default PC.
            reader = getattr(history_store, "get_pc_output_dispatch_for_owner", None)
            if not callable(reader):
                raise ValueError("output dispatch authority unavailable")
            owned = await reader(user_id=uid, dispatch_id=dispatch["dispatch_id"])
            if not isinstance(owned, dict) or owned.get("run_id") != payload["run_id"]:
                raise ValueError("output dispatch unavailable")
            device_id = owned.get("device_id")
        if not isinstance(device_id, str) or not device_id:
            raise ValueError("output device unavailable")
        ref = await store(user_id=uid, subject_id=payload["subject_id"], run_id=payload["run_id"],
                          device_id=device_id, dispatch_id=dispatch["dispatch_id"], content=output)
        if not isinstance(ref, dict) or not isinstance(ref.get("handle"), str):
            raise ValueError("output reference unavailable")
        preview = ref.get("head", "") + ("\n...\n" if ref.get("truncated") else "") + ref.get("tail", "")
        return {"output": preview, "output_ref": ref}, None
    except Exception:
        return None, _error(503, "pc_output_store_unavailable")


def _engine_pc_job_response(response: JSONResponse, mode: str) -> JSONResponse:
    if mode != "job_start" or response.status_code != 200:
        return response
    dispatch = json.loads(response.body)["dispatch"]
    return _response({"ok": True, "result": {
        "job_id": dispatch["dispatch_id"], "state": dispatch["state"],
        "device_id": dispatch["device_id"], "kind": dispatch["kind"],
    }})


async def _engine_pc_output_call(history_store: Any, *, payload: dict, uid: str, device_id: str) -> JSONResponse:
    """Read only the current authenticated owner/run/device's opaque output."""
    mode = payload["mode"]
    owner = {"user_id": uid, "subject_id": payload["subject_id"],
             "run_id": payload["run_id"], "device_id": device_id}
    try:
        if mode == "store_output":
            if (payload.get("source") != "pc_batch" or not isinstance(payload.get("output"), str)
                or not isinstance(payload.get("tool_call_ref"), str)
                or _PC_FILES_SAFE_REF.fullmatch(payload["tool_call_ref"]) is None):
                return _error(422, "pc_output_source_invalid")
            method = getattr(history_store, "store_pc_output", None)
            if not callable(method):
                return _error(503, "pc_output_store_unavailable")
            result = await method(**owner, dispatch_id="", content=payload["output"],
                                  source="pc_batch:" + payload["tool_call_ref"])
        else:
            handle = payload.get("handle")
            if not isinstance(handle, str) or re.fullmatch(r"[0-9a-f]{64}", handle) is None:
                return _error(422, "pc_output_handle_invalid")
            if mode == "read_output":
                method = getattr(history_store, "read_pc_output", None)
                if not callable(method):
                    return _error(503, "pc_output_store_unavailable")
                result = await method(**owner, handle=handle, offset=payload["offset"], length=payload["length"])
            else:
                query = payload.get("query")
                if not isinstance(query, str) or not query:
                    return _error(422, "pc_output_query_invalid")
                method = getattr(history_store, "search_pc_output", None)
                if not callable(method):
                    return _error(503, "pc_output_store_unavailable")
                result = await method(**owner, handle=handle, query=query)
        if not isinstance(result, dict):
            raise ValueError("invalid output response")
        return _response({"ok": True, "result": result})
    except (FileNotFoundError, PermissionError, HistoryForbidden):
        return _error(404, "pc_output_unavailable")
    except Exception:
        return _error(503, "pc_output_store_unavailable")


PC_IMAGE_ENVELOPE_PREFIX = "PADIEM_IMAGE_CONTENT:"
PC_IMAGE_LONG_EDGE_MAX = 2000
PC_IMAGE_BYTE_CAP = 300_000


def _pc_image_projection(output: str) -> tuple[str, dict[str, str] | None]:
    """#7447: one image envelope becomes a bounded note + one MCP image block.

    This handler is where the MCP/file lanes read a stored PC read result, so
    the envelope the PC agent frames is projected here as well as in the
    Engine driver. Anything that does not parse returns untouched.
    """
    if not output.startswith(PC_IMAGE_ENVELOPE_PREFIX):
        return output, None
    head, _, encoded = output[len(PC_IMAGE_ENVELOPE_PREFIX):].partition(":")
    mime = head.strip()
    if mime not in ("image/png", "image/jpeg", "image/webp", "image/gif") or not encoded:
        return output, None
    import base64
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return output, None
    note = (f"이미지 파일을 읽었습니다: {mime}, {len(raw):,}바이트. "
            "(축소 없이 원본 그대로)")
    try:
        import io
        from PIL import Image

        image = Image.open(io.BytesIO(raw))
        source_size = image.size
        long_edge = max(image.size)
        if long_edge > PC_IMAGE_LONG_EDGE_MAX:
            ratio = PC_IMAGE_LONG_EDGE_MAX / long_edge
            image = image.resize(
                (max(1, round(image.size[0] * ratio)),
                 max(1, round(image.size[1] * ratio))))
            note_extra = f" 긴 변 {long_edge}px를 {PC_IMAGE_LONG_EDGE_MAX}px로 축소."
        else:
            note_extra = ""
        fmt = "PNG" if mime == "image/png" else (
            "JPEG" if mime == "image/jpeg" else "PNG")
        buf = io.BytesIO()
        image.save(buf, format=fmt)
        if len(buf.getvalue()) > PC_IMAGE_BYTE_CAP:
            converted = image.convert("RGB")
            for quality, edge in ((80, None), (50, 1280), (35, 800)):
                buf = io.BytesIO()
                step = converted
                if edge and max(step.size) > edge:
                    ratio = edge / max(step.size)
                    step = step.resize((max(1, round(step.size[0] * ratio)),
                                        max(1, round(step.size[1] * ratio))))
                step.save(buf, format="JPEG", quality=quality)
                fmt = "JPEG"
                if len(buf.getvalue()) <= PC_IMAGE_BYTE_CAP:
                    break
            image = step
            note_extra = f" 용량 상한에 맞춰 JPEG({quality})로 재부호화.{note_extra}"
        out_mime = {"PNG": "image/png", "JPEG": "image/jpeg"}[fmt]
        data = buf.getvalue()
        if len(data) > PC_IMAGE_BYTE_CAP:
            # Three compression passes are not a proof of a bound. Fail closed.
            return ("이미지 크기 제한을 초과하여 그림을 보내지 못했습니다.",
                    {"type": "error", "code": "pc_image_size_limit_exceeded",
                     "resized": image.size != source_size,
                     "original_size": list(source_size),
                     "result_size": list(image.size),
                     "original_bytes": len(raw), "result_bytes": len(data)})
        note = (
            f"이미지 파일을 읽었습니다: {mime}, "
            f"{source_size[0]}x{source_size[1]} → {image.size[0]}x{image.size[1]}, "
            f"{len(data):,}바이트.{note_extra}"
        )
    except Exception:
        # Pillow unavailable or an undecodable frame: the projection still
        # carries what the PC actually read, with no downscale claim — but an
        # original above PC_IMAGE_BYTE_CAP never ships unscaled. Without
        # Pillow there is no way to meet the cap, so the caller gets the
        # bounded text only (CTO decision 2026-11-13, #7447 follow-up).
        if len(raw) > PC_IMAGE_BYTE_CAP:
            return ("이미지 크기 제한을 초과하여 그림을 보내지 못했습니다.",
                    {"type": "error", "code": "pc_image_size_limit_exceeded",
                     "resized": False, "original_size": None, "result_size": None,
                     "original_bytes": len(raw), "result_bytes": len(raw)})
        return note, {"type": "image", "mimeType": mime,
                      "data": base64.b64encode(raw).decode("ascii"),
                      "resized": False, "original_size": None, "result_size": None,
                      "original_bytes": len(raw), "result_bytes": len(raw)}
    return note, {"type": "image", "mimeType": out_mime,
                  "data": base64.b64encode(data).decode("ascii"),
                  "resized": image.size != source_size,
                  "original_size": list(source_size), "result_size": list(image.size),
                  "original_bytes": len(raw), "result_bytes": len(data)}
