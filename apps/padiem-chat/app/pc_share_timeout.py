"""#8037 네트워크 공유 C — 공유 경로 명령의 20초 제한과 닫힌 오류 코드.

등록·승인된 네트워크 공유(UNC ``//server/share``)를 다루는 PC 읽기·목록·검색
명령은 자체 시간 제한을 가진다. 끊기거나 응답 없는 공유가 PC 명령 줄을 점유하지
않게, 제한을 넘긴 명령은 정리되고 ``pc_share_unavailable`` 로 닫힌다. 로컬
드라이브 명령에는 이 제한이 없다 — 기존 동작 그대로다.

판정은 서버가 스테이징 시점에 내린다: 승인된 루트 집합에서 공유 주소를 고르고,
그 철자(#7978/#8041) 그대로 ``$padiemShareTargets`` 리터럴을 명령 머리에 싣는다.
커넥터는 이 선언만 읽고 시간을 재며, 경로 권위(승인된 공유만)는 넓히지 않는다.
자격 증명은 이 모듈 어디에도 없다 — 공유 접근 자격은 PC의 사용자 세션에 남는다.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from padiem_ai_core.powershell_literal import ps_utf8_literal

#: CTO 결정(2026-11-19): 공유 경로 PC 명령의 자체 시간 제한.
PC_SHARE_COMMAND_TIMEOUT_SECONDS = 20
#: 제한을 넘긴 공유 명령이 닫히는 코드. Engine·커넥터·Chat이 같은 이름을 쓴다.
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
#: 커넥터가 읽는 선언 변수. 명령 본문은 이 이름으로 공유 판정을 한다.
PC_SHARE_TARGETS_VARIABLE = "$padiemShareTargets"


def _share_spelling(root: Any) -> str | None:
    """승인된 루트 하나가 공유 주소면 그 Windows 철자, 아니면 None.

    로컬 드라이브(``C:``·``D:/폴더``)는 공유가 아니다. 매핑 드라이브 글자는
    별칭일 뿐이므로(#8036) 공유 주소만 판정한다.
    """
    if not isinstance(root, str) or not root:
        return None
    text = root.strip().replace("\\", "/").rstrip("/")
    if not text.startswith("//"):
        return None
    parts = [part for part in text[2:].split("/") if part]
    if len(parts) < 2:
        return None
    return "\\\\" + "\\".join(parts)


def share_roots_of(roots: Iterable[Any] | None) -> list[str]:
    """루트 집합에서 공유 주소만, 승인된 철자 그대로, 중복 없이."""
    found: list[str] = []
    for root in roots or ():
        path = root.get("path") if isinstance(root, dict) else root
        spelling = _share_spelling(path)
        if spelling is not None and spelling not in found:
            found.append(spelling)
    return found


def share_command_prefix(roots: Iterable[Any] | None) -> str:
    """공유 선언 한 줄. 공유가 없으면 빈 문자열 — 로컬 명령은 그대로다.

    값은 base64 UTF-8 리터럴(#7973)이라 콘솔 코드 페이지가 철자를 바꾸지 못하고,
    선언은 명령의 어떤 폴더 연산보다 먼저 실행된다.
    """
    shares = share_roots_of(roots)
    if not shares:
        return ""
    literals = ",".join(ps_utf8_literal(spelling) for spelling in shares)
    return PC_SHARE_TARGETS_VARIABLE + "=@(" + literals + ")\n"


def share_timeout_verdict_body() -> str:
    """시간 초과 시 커넥터가 결과로 싣는 닫힌 JSON 본문."""
    return json.dumps(
        {
            "ok": False,
            "error": PC_SHARE_UNAVAILABLE_CODE,
            "message": PC_SHARE_UNAVAILABLE_MESSAGE_KO,
            "message_en": PC_SHARE_UNAVAILABLE_MESSAGE_EN,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


__all__ = [
    "PC_SHARE_COMMAND_TIMEOUT_SECONDS",
    "PC_SHARE_TARGETS_VARIABLE",
    "PC_SHARE_UNAVAILABLE_CODE",
    "PC_SHARE_UNAVAILABLE_MESSAGE_EN",
    "PC_SHARE_UNAVAILABLE_MESSAGE_KO",
    "share_command_prefix",
    "share_roots_of",
    "share_timeout_verdict_body",
]