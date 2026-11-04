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
NDJSON_MEDIA_TYPE = "application/x-ndjson"

_LOG = logging.getLogger("padiem_chat.orchestration_stream")


def orchestration_stream_enabled(source: Any) -> bool:
    """서버가 소유한 스위치. 바인딩(Worker)과 환경변수(local host)를 같은 값으로 읽는다."""
    value = binding_value(source, STREAM_FLAG_ENV)
    return (value.strip() if isinstance(value, str) else "").lower() in {"1", "true", "on"}


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
                if "result" in record:
                    result = record["result"]
                    break
                # heartbeat·event·pc_progress는 일반 답변 화면에 쓰지 않는다.
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
    "NDJSON_MEDIA_TYPE",
    "STREAM_FLAG_ENV",
    "line",
    "ndjson_answer",
    "orchestration_stream_enabled",
    "wants_ndjson",
]
