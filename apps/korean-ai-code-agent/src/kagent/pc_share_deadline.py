"""#8037 네트워크 공유 C — 커넥터 쪽 공유 명령 20초 제한.

서버가 스테이징 시점에 선언한 공유 주소(``share_roots``)와 명령 머리의
``$padiemShareTargets`` 리터럴만 읽는다. 둘이 일치할 때만 그 명령은 공유
명령이고, 자체 시간 제한(기본 20초)을 가진다. 로컬 드라이브 명령과 선언 없는
명령은 기존 그대로 — 제한 없음.

시간 초과는 닫힌 오류 ``pc_share_unavailable`` 로 끝나고, 실행 중이던 공유
명령은 정리(stop)되어 다음 명령이 막히지 않는다. 자격 증명은 어디에도 싣지
않는다. 시계는 주입 가능해 시험이 실제 시간을 기다리지 않는다.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Callable

#: CTO 결정(2026-11-19): 공유 경로 PC 명령의 자체 시간 제한.
PC_SHARE_COMMAND_TIMEOUT_SECONDS = 20
#: 닫힌 오류 코드 — Chat·Engine과 같은 이름.
PC_SHARE_UNAVAILABLE_CODE = "pc_share_unavailable"
#: 사용자 안내 문구 (ko·en).
PC_SHARE_UNAVAILABLE_MESSAGE_KO = (
    "네트워크 공유 폴더에 연결할 수 없어요. "
    "회사 네트워크에 연결돼 있는지 확인해 주세요."
)
PC_SHARE_UNAVAILABLE_MESSAGE_EN = (
    "Can't reach the network share folder. "
    "Please check that you're connected to your company network."
)
#: 서버가 명령 머리에 싣는 선언 변수(#8037). 이 선언이 있는 명령만 판정한다.
#: 선언은 한 줄이다 — 줄 끝에서 닫는 괄호를 찾는다(리터럴 안의 괄호는 base64라
#: ')'가 없다).
_SHARE_DECLARATION = re.compile(
    r"\$padiemShareTargets\s*=\s*@\((.*)\)\s*$", re.IGNORECASE | re.MULTILINE
)
_BASE64_LITERAL = re.compile(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)")


def declared_share_roots(command_text: str | None) -> list[str] | None:
    """명령 머리의 공유 선언을 디코드한다. 선언이 없으면 None.

    선언은 서버가 승인된 루트에서 만든 base64 UTF-8 리터럴(#7973)이다. 읽을 수
    없는 선언은 공유 선언이 아닌 것으로 둔다 — 제한을 발명하지 않는다.
    """
    if not isinstance(command_text, str) or not command_text:
        return None
    match = _SHARE_DECLARATION.search(command_text)
    if match is None:
        return None
    roots: list[str] = []
    for blob in _BASE64_LITERAL.findall(match.group(1)):
        try:
            value = base64.b64decode(blob, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        if not value or any(ord(ch) < 32 for ch in value):
            return None
        roots.append(value)
    return roots or None


def _folded(value: str) -> str:
    return value.strip().replace("/", "\\").rstrip("\\").casefold()


def share_command_deadline(
    *,
    command_text: str | None,
    share_roots: Any,
    timeout_seconds: int = PC_SHARE_COMMAND_TIMEOUT_SECONDS,
) -> int | None:
    """이 명령이 공유 명령이면 적용할 초 단위 제한, 아니면 None.

    서버가 폴드 응답에 실어 보낸 승인 공유 목록과 명령의 선언이 일치할 때만
    제한이 선다. 어느 한쪽이라도 없거나 다르면 기존 동작(제한 없음) 그대로다.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        return None
    if not isinstance(share_roots, (list, tuple)) or not share_roots:
        return None
    declared = declared_share_roots(command_text)
    if not declared:
        return None
    approved = {_folded(item) for item in share_roots if isinstance(item, str) and item}
    if not approved:
        return None
    if not all(_folded(item) in approved for item in declared):
        return None
    return timeout_seconds


def share_unavailable_body() -> bytes:
    """시간 초과 공유 명령의 닫힌 결과 본문 (UTF-8 JSON)."""
    return json.dumps(
        {
            "ok": False,
            "error": PC_SHARE_UNAVAILABLE_CODE,
            "message": PC_SHARE_UNAVAILABLE_MESSAGE_KO,
            "message_en": PC_SHARE_UNAVAILABLE_MESSAGE_EN,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def is_share_unavailable_body(body: bytes | str | None) -> bool:
    """결과 본문이 닫힌 공유 불가 판정인지."""
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return False
    if not isinstance(body, str):
        return False
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(parsed, dict)
        and parsed.get("ok") is False
        and parsed.get("error") == PC_SHARE_UNAVAILABLE_CODE
    )


class ShareDeadline:
    """주입된 시계로 재는 공유 명령 제한.

    ``wrap_cancel_probe``는 포트가 매 읽기 조각마다 부르는 중지 probe에 제한
    검사를 겹친다: 주입 시계가 제한을 넘으면 ``on_expire``(공유 명령 정리)를
    한 번 부르고 True를 돌려줘, 포트가 기존 중지 경로로 클라이언트를 끝내고
    ``cancelled`` 관측을 보고하게 한다. 시계는 ``clock``으로 주입한다 —
    시험은 실제 시간을 기다리지 않는다. 정리는 최선 노력이고 실패해도
    결과 판정을 바꾸지 않는다.
    """

    def __init__(
        self,
        *,
        seconds: int,
        clock: Callable[[], float] | None = None,
        on_expire: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 1:
            raise ValueError("the share deadline must be a positive integer")
        self._seconds = seconds
        self._clock = clock if callable(clock) else time.monotonic
        self._on_expire = on_expire
        self._started = self._clock()
        self._expired = False

    @property
    def seconds(self) -> int:
        return self._seconds

    @property
    def expired(self) -> bool:
        return self._expired

    def check(self) -> bool:
        """제한을 넘었으면 한 번 정리하고 True. 아직이면 False."""
        if self._expired:
            return True
        if self._clock() - self._started < self._seconds:
            return False
        self._expired = True
        if self._on_expire is not None:
            try:
                self._on_expire()
            except Exception:
                pass
        return True

    def wrap_cancel_probe(
        self, probe: Callable[[], bool] | None
    ) -> Callable[[], bool]:
        def bounded() -> bool:
            if self.check():
                return True
            if probe is None:
                return False
            try:
                return probe() is True
            except Exception:
                return False

        return bounded


__all__ = [
    "PC_SHARE_COMMAND_TIMEOUT_SECONDS",
    "PC_SHARE_UNAVAILABLE_CODE",
    "PC_SHARE_UNAVAILABLE_MESSAGE_EN",
    "PC_SHARE_UNAVAILABLE_MESSAGE_KO",
    "ShareDeadline",
    "declared_share_roots",
    "is_share_unavailable_body",
    "share_command_deadline",
    "share_unavailable_body",
]