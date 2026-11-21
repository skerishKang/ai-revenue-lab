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
import inspect
import json
import re
import time
from typing import Any, Callable

from .local_agent_search_silent_cap import recursive_search_silent_cap


def _port_accepts_silent_cap(port: Any) -> bool:
    """True when ``port.run_command`` accepts ``silent_cap_seconds`` (#8048).

    Older ports and the contract tests' doubles keep their exact signature;
    handing them an unknown keyword would turn a TypeError into a false
    ``no_reply``. A port that takes ``**kwargs`` accepts anything.
    """

    try:
        parameters = inspect.signature(port.run_command).parameters
    except (TypeError, ValueError):
        return False
    return "silent_cap_seconds" in parameters or any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    )


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


def poll_share_roots(dispatch: dict[str, Any], kind: str) -> tuple[str, ...] | None:
    """폴드 응답의 공유 선언을 검증해 싣는다. 잘못된 값은 선언 없음(기존 동작)."""
    if kind != "command":
        return None
    supplied = dispatch.get("share_roots")
    if not isinstance(supplied, list) or not supplied:
        return None
    if all(
        isinstance(item, str) and 0 < len(item) <= 32000
        and not any(ord(ch) < 32 for ch in item)
        for item in supplied
    ):
        return tuple(supplied)
    return None


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


def share_bound_seconds(dispatch: Any) -> int | None:
    """이 디스패치가 공유 명령이면 적용할 초 단위 제한, 아니면 None."""
    return share_command_deadline(
        command_text=getattr(dispatch, "command_text", None),
        share_roots=getattr(dispatch, "share_roots", None),
    )


def command_run_kwargs(
    *, executor: Any, dispatch: Any, phase: Callable[[str], None],
    deadline_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """명령 포트 호출 인자 — 기존 무제한 대기 계약 그대로(#5983/#5895/#7841).

    소유자 중지 probe가 명령을 끝내고, 선언된 공유 명령의 20초 제한은 같은
    probe에 겹쳐진다(#8037). 그 외 어떤 명령에도 제한을 만들지 않는다.

    #8048: 재귀 검색 명령은 침묵 상한을 190초로 올린다(기본 60초). 검색
    스크립트 자체가 180초 벽시계로 끝나므로, 60초 침묵 상한이 정당한 검색을
    자르지 않게 한다. 이 인자를 받는 포트에만 싣는다 — 구 포트·시험 더블의
    서명을 바꾸지 않는다.
    """
    kwargs = dict(
        node_ref=dispatch.node_ref,
        command=dispatch.command_text or "",
        timeout_seconds=None,
        phase_observer=phase,
        dispatch_id=getattr(dispatch, "dispatch_id", None),
        keep_dispatch_ids=executor.active_dispatch_ids(),
        line_guard=executor._line_guard(dispatch),
        **deadline_kwargs,
    )
    cap = recursive_search_silent_cap(getattr(dispatch, "command_text", None))
    if cap is not None and _port_accepts_silent_cap(executor._command_port):
        kwargs["silent_cap_seconds"] = cap
    return kwargs


def stop_share_command(
    port: Any, dispatch: Any, phase: Callable[[str], None]
) -> None:
    """제한을 넘긴 공유 명령을 PC에서 정리한다 — 소유자 중지와 같은 경로.

    최선 노력: 정리가 확인되지 않아도 결과 판정(닫힌 코드)은 그대로다.
    """
    killer = getattr(port, "kill_command_process", None)
    if not callable(killer):
        return
    try:
        killer(
            node_ref=dispatch.node_ref,
            dispatch_id=str(getattr(dispatch, "dispatch_id", "") or ""),
        )
    except Exception:
        pass


def run_share_bounded_command(
    *,
    port: Any,
    dispatch: Any,
    share_seconds: int | None,
    clock: Callable[[], float] | None,
    stop_on_pc: Callable[..., Any],
    phase: Callable[[str], None],
    cancel_probe: Callable[[], bool],
    run_kwargs: dict[str, Any],
) -> tuple[Any, "ShareDeadline | None"]:
    """공유 선언 명령만 제한을 겹쳐 포트를 부른다. (관측, 제한)을 돌려준다.

    제한이 없는 명령은 포트 호출 그대로다. 제한을 넘긴 공유 명령은 정리(stop)가
    먼저 돌고, 닫힌 본문은 호출자가 결과로 싣는다.
    """
    deadline = None
    if share_seconds is not None:
        deadline = ShareDeadline(
            seconds=share_seconds,
            clock=clock if callable(clock) else time.monotonic,
            on_expire=lambda: stop_on_pc(port, dispatch, phase),
        )
        cancel_probe = deadline.wrap_cancel_probe(cancel_probe)
    observed = port.run_command(cancel_probe=cancel_probe, **run_kwargs)
    return observed, deadline


__all__ = [
    "PC_SHARE_COMMAND_TIMEOUT_SECONDS",
    "PC_SHARE_UNAVAILABLE_CODE",
    "PC_SHARE_UNAVAILABLE_MESSAGE_EN",
    "PC_SHARE_UNAVAILABLE_MESSAGE_KO",
    "ShareDeadline",
    "declared_share_roots",
    "is_share_unavailable_body",
    "poll_share_roots",
    "run_share_bounded_command",
    "share_command_deadline",
    "share_unavailable_body",
]