"""일반 답변의 서버 스트리밍(#6742).

플래그(``PADIEM_CHAT_ORCHESTRATION_STREAM``, 기본 off)가 켜져 있고 요청이 스트림을
요청했을 때만 NDJSON으로 답한다. 꺼져 있으면 라우트는 지금과 같은 JSON을 그대로 쓴다.

줄 형식(한 줄에 JSON 하나, UTF-8):
  {"type":"meta","stream":true}
  {"type":"delta","text":"…"}            (1개 이상)
  {"type":"done","done":true,…}          (정확히 1개, 저장 뒤)
  {"type":"error","code":"…"}            (실패 시 1개)

저장 정책: 검증된 완료 결과에서만, done 직전에 한 번 저장한다. 스트림이 중간에
끊기면(브라우저 절단·엔진 중단) 저장하지 않는다 — 지금 JSON 경로가 실패하면
저장하지 않는 것과 같다. 부분 저장은 하지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from .orchestration_bridge import B62OrchestrationError
from .orchestration_timing import OrchestrationTiming
from .worker_config import binding_value

STREAM_FLAG_ENV = "PADIEM_CHAT_ORCHESTRATION_STREAM"
STREAM_USERS_ENV = "PADIEM_CHAT_ORCHESTRATION_STREAM_USERS"
NDJSON_MEDIA_TYPE = "application/x-ndjson"

_LOG = logging.getLogger("padiem_chat.orchestration_stream")

PROGRESS_EVENT_KINDS = frozenset({
    "run_started",
    "context_prepared",
    "plan_created",
    "tool_started",
    "tool_completed",
    "tool_failed",
})
PC_PROGRESS_STAGES = frozenset({"accepted", "picked_up", "executing", "result"})
PROGRESS_KINDS = PROGRESS_EVENT_KINDS | {"pc_progress", "heartbeat"}
HEARTBEAT_MIN_INTERVAL_SECONDS = 5.0

_WEB_TOOL_IDS = frozenset({"web_search", "search_web"})
_PC_TOOL_IDS = frozenset({
    "pc_tool", "query_drives", "files_list", "files", "files_write", "browser",
    "claw.pc.query_drives", "claw.pc.list_files", "claw.pc.read_file", "claw.pc.write_file",
    "claw.pc.browser_open", "claw.pc.browser_read", "claw.pc.browser_screenshot", "claw.pc.browser_act",
})


def _elapsed_ms(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _progress_label(kind: str, *, stage: str | None = None, tool_name: Any = None) -> str:
    tool_id = tool_name if isinstance(tool_name, str) else ""
    if kind == "tool_started":
        if tool_id in _WEB_TOOL_IDS:
            return "웹 확인 중"
        if tool_id in _PC_TOOL_IDS:
            return "PC 작업 중"
        return "도구 작업 중"
    if kind == "tool_completed":
        if tool_id in _WEB_TOOL_IDS:
            return "웹 확인 완료"
        if tool_id in _PC_TOOL_IDS:
            return "PC 작업 완료"
        return "도구 작업 완료"
    if kind == "tool_failed":
        if tool_id in _WEB_TOOL_IDS:
            return "웹 확인이 필요해요"
        if tool_id in _PC_TOOL_IDS:
            return "PC 작업 확인이 필요해요"
        return "도구 작업 확인이 필요해요"
    if kind == "run_started":
        return "질문 확인 중"
    if kind == "context_prepared":
        return "질문 확인 중"
    if kind == "plan_created":
        return "답변 방향 확인"
    if kind == "pc_progress":
        return {
            "accepted": "PC 요청 접수",
            "picked_up": "PC 작업 인계",
            "executing": "PC 작업 중",
            "result": "PC 결과 확인 중",
        }[stage or ""]
    return "작업 진행 중"


class ProgressFrameBuilder:
    """Project Engine progress records to a small, public-safe Chat frame."""

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or time.monotonic
        self._sequence = 0
        self._last_heartbeat_at: float | None = None

    def frame(
        self,
        kind: str,
        *,
        stage: str | None = None,
        elapsed_ms: Any = None,
        tool_name: Any = None,
    ) -> dict[str, Any] | None:
        if not isinstance(kind, str) or kind not in PROGRESS_KINDS:
            return None
        if kind == "pc_progress":
            if not isinstance(stage, str) or stage not in PC_PROGRESS_STAGES:
                return None
        elif stage is not None:
            return None
        self._sequence += 1
        frame: dict[str, Any] = {
            "type": "progress",
            "kind": kind,
            "sequence": self._sequence,
            "label": _progress_label(kind, stage=stage, tool_name=tool_name),
        }
        if stage is not None:
            frame["stage"] = stage
        safe_elapsed = _elapsed_ms(elapsed_ms)
        if safe_elapsed is not None:
            frame["elapsed_ms"] = safe_elapsed
        return frame

    def from_engine_record(self, record: Any) -> dict[str, Any] | None:
        if not isinstance(record, dict):
            return None
        event = record.get("event")
        if isinstance(event, dict):
            kind = event.get("kind")
            if not isinstance(kind, str) or kind not in PROGRESS_EVENT_KINDS:
                return None
            metadata = event.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            tool_name = metadata.get("tool_id") or metadata.get("tool_name")
            return self.frame(kind, tool_name=tool_name)

        pc_progress = record.get("pc_progress")
        if isinstance(pc_progress, dict):
            return self.frame(
                "pc_progress",
                stage=pc_progress.get("stage"),
                elapsed_ms=pc_progress.get("elapsed_ms"),
            )

        heartbeat = record.get("heartbeat")
        if isinstance(heartbeat, dict):
            now = self._clock()
            if (
                self._last_heartbeat_at is not None
                and now - self._last_heartbeat_at < HEARTBEAT_MIN_INTERVAL_SECONDS
            ):
                return None
            self._last_heartbeat_at = now
            return self.frame("heartbeat", elapsed_ms=heartbeat.get("elapsed_ms"))
        return None


def _parse_stream_allowlist(source: Any) -> set[str]:
    """Parse comma-separated user allowlist. Ignore malformed values silently."""
    value = binding_value(source, STREAM_USERS_ENV)
    if not isinstance(value, str):
        return set()
    allowlist: set[str] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if len(item) > 256:
            continue
        allowlist.add(item)
    return allowlist


def orchestration_stream_enabled(source: Any, user_id: str | None = None) -> bool:
    """서버 스위치 판정. Worker와 환경변수(local host) 양쪽에서 값을 읽는다.

    If global flag is on, everyone gets streaming. If global flag is off but user
    is logged in and in allowlist, that user gets streaming. Guests never enabled by allowlist.
    """
    global_value = binding_value(source, STREAM_FLAG_ENV)
    global_enabled = (global_value.strip() if isinstance(global_value, str) else "").lower() in {"1", "true", "on"}
    if global_enabled:
        return True
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        return False
    allowlist = _parse_stream_allowlist(source)
    return user_id.strip() in allowlist


def wants_ndjson(raw: Any, accept: str | None) -> bool:
    """브라우저가 스트림을 요청했는가. 본문 ``stream: 1`` 또는 NDJSON Accept 헤더."""
    if isinstance(raw, dict):
        flag = raw.get("stream")
        if flag is True or flag == 1:
            return True
        if isinstance(flag, str) and flag.strip().lower() in {"1", "true"}:
            return True
    return NDJSON_MEDIA_TYPE in (accept or "").lower()


def line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


async def _bounded_records(stream: Any, deadline: float | None) -> AsyncIterator[Any]:
    """Yield answer records while the front-door budget still has time left.

    The 55s B14 chain is not the outer deadline: the front gives an answer request
    60s. When the remaining budget is spent, raising here lets the route answer
    with the same Korean timeout copy instead of letting Cloudflare's edge answer
    first (답변 시간 예산).
    """
    iterator = stream.__aiter__()
    while True:
        if deadline is None:
            try:
                yield await iterator.__anext__()
            except StopAsyncIteration:
                return
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise asyncio.TimeoutError
        try:
            record = await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
        except StopAsyncIteration:
            return
        yield record


async def ndjson_answer(
    *,
    bridge: Any,
    stream_kwargs: dict[str, Any],
    buffered_kwargs: dict[str, Any],
    timing: OrchestrationTiming,
    on_completed: Any,
    timeout_seconds: float | None = None,
) -> AsyncIterator[bytes]:
    """엔진 NDJSON을 브라우저 NDJSON으로 옮긴다.

    엔진이 스트림을 주지 못하면(첫 조각 전 실패) 같은 요청을 완성 응답으로 한 번 더
    보내 한 덩어리 delta로 대체한다. 첫 delta 뒤의 실패는 다시 보내지 않는다 —
    같은 답변을 두 번 쓰지 않기 위해서다. 시간 예산이 끝나면 재시도하지 않고
    기존 한국어 시간 초과 코드만 보낸다.
    """
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    text_seen = False
    result = None
    progress = ProgressFrameBuilder()
    try:
        yield line({"type": "meta", "stream": True})
        stream = bridge.start_stream(**stream_kwargs)
        try:
            async for record in _bounded_records(stream, deadline):
                if not isinstance(record, dict):
                    continue
                if "text_delta" in record:
                    delta = (record.get("text_delta") or {}).get("delta")
                    if isinstance(delta, str) and delta:
                        if not text_seen:
                            timing.mark("first_token")
                        text_seen = True
                        yield line({"type": "delta", "text": delta})
                    continue
                progress_frame = progress.from_engine_record(record)
                if progress_frame is not None:
                    yield line(progress_frame)
                if any(key in record for key in ("event", "pc_progress", "heartbeat")):
                    continue
                if "result" in record:
                    result = record["result"]
                    break
        except asyncio.TimeoutError:
            yield line({"type": "error", "code": "upstream_timeout"})
            return
        except B62OrchestrationError as exc:
            if exc.code in {"upstream_timeout", "timeout"}:
                yield line({"type": "error", "code": "upstream_timeout"})
                return
            if text_seen:
                yield line({"type": "error", "code": exc.code})
                return
            # A non-timeout Engine refusal before the first token keeps the
            # existing one-shot buffered fallback.
            _LOG.info("orchestration_stream_fallback stage=start")
        except Exception:
            if text_seen:
                yield line({"type": "error", "code": "invalid_engine_stream"})
                return
            # 스트림을 못 받았다: 아래 완성 응답 경로로 대체한다.
            _LOG.info("orchestration_stream_fallback stage=start")
        finally:
            close = getattr(stream, "aclose", None)
            if callable(close):
                try:
                    await close()
                except Exception:
                    pass
        if result is None:
            if deadline is None:
                result = await bridge.start(**buffered_kwargs)
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    yield line({"type": "error", "code": "upstream_timeout"})
                    return
                result = await asyncio.wait_for(
                    bridge.start(**buffered_kwargs), timeout=remaining,
                )
        answer = getattr(result, "answer", None)
        if not isinstance(answer, str) or not answer:
            yield line({"type": "error", "code": "engine_execution_failed"})
            return
        if not text_seen:
            timing.mark("first_token")
            yield line({"type": "delta", "text": answer})
        timing.mark("engine")
        fields = await on_completed(result)
        timing.mark("save")
        yield line({"type": "done", "done": True, **dict(fields or {})})
    except asyncio.TimeoutError:
        yield line({"type": "error", "code": "upstream_timeout"})
    except B62OrchestrationError as exc:
        yield line({"type": "error", "code": exc.code})
    except Exception:
        # 원인 문자열·본문은 내보내지 않는다. 코드만 닫힌 어휘로 보낸다.
        yield line({"type": "error", "code": "engine_execution_failed"})
    finally:
        timing.emit()


__all__ = [
    "HEARTBEAT_MIN_INTERVAL_SECONDS",
    "NDJSON_MEDIA_TYPE",
    "PC_PROGRESS_STAGES",
    "PROGRESS_EVENT_KINDS",
    "PROGRESS_KINDS",
    "ProgressFrameBuilder",
    "STREAM_FLAG_ENV",
    "STREAM_USERS_ENV",
    "line",
    "ndjson_answer",
    "orchestration_stream_enabled",
    "wants_ndjson",
]
