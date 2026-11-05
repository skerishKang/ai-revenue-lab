"""#5994 D3 후속 — 허용 루트 안 경로가 정션/심볼릭 링크를 통과하는지 판정.

PC 집행기(읽기·쓰기·이동·삭제·목록)가 파일을 만지기 전에 이 판정 하나를 통과해야
한다. 의존성 없는 모듈(os·stat만)이라 어떤 실행기에서도 같은 파일을 직접 적재해
쓸 수 있고, 레인마다 판정이 갈라지지 않는다.

루트 자체가 링크인 경우는 소유자의 허가 결정이므로 검사하지 않는다(기존 동작
유지). 루트 아래의 모든 폴더와 대상 자체만 본다.
"""
from __future__ import annotations

import os
import stat

_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (junction·symlink·mount)


def walk_hits_reparse_point(granted_root: str, file_path: str) -> bool:
    """루트→대상의 모든 상위 폴더와 대상이 정션/링크를 통과하면 True.

    이 호스트가 실제로 걸을 수 있는 경로만 판정한다. 11-05 09:22:09처럼 컴2
    중계 실행기가 다른 PC의 Windows 경로("C:\\...")를 받으면 그 경로는 컴2의
    파일 시스템에 없으므로 판정하지 않고 False를 돌려준다 — 판정할 수 없다는
    사실은 우회의 증거가 아니다. 그 판정은 PC 쪽 PowerShell 가드가 한다.

    끝 구분자는 하나로 접어서 비교한다("C:\\"와 "C:/"는 같은 루트다). 정규화된
    대상 경로가 허용 루트 밖이면(그 자체로 우회) True다. 루트 자체는 검사하지
    않는다 — 소유자가 허가한 폴더의 위치는 소유자의 결정이다. 루트 안쪽으로 다시
    향하는 링크(배포 구조의 심링크)는 우회가 아니므로 통과한다.
    """
    root_full = _host_path(granted_root)
    target_full = _host_path(file_path)
    if root_full is None or target_full is None:
        return False  # 이 호스트에서 판정할 수 있는 경로가 아니다
    root_prefix = root_full.rstrip(os.sep) + os.sep
    if not (target_full + os.sep).lower().startswith(root_prefix.lower()):
        return True  # 정규화 경로가 루트 밖 — 그 자체로 우회
    remainder = target_full[len(root_prefix):]
    walk = root_full
    for segment in remainder.replace("\\", "/").split("/"):
        if not segment:
            continue
        walk = os.path.join(walk, segment)
        try:
            info = os.lstat(walk)  # 링크를 따라가지 않는 stat
        except OSError:
            return False  # 아직 없는 조각은 링크일 수 없다
        if _is_reparse(info) and not _stays_inside(root_full, walk):
            return True
    return False


def _host_path(value: str) -> str | None:
    """이 호스트가 실제로 걸을 수 있는 절대 경로의 정규형, 아니면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if os.name == "posix":
        if not text.startswith("/"):
            return None  # 다른 PC의 Windows·UNC 경로 — 이 호스트가 판정할 수 없다
    else:
        drive, rest = os.path.splitdrive(text)
        if not drive:
            return None
        if len(text) == 2 and not rest:
            # "C:"는 그 드라이브의 현재 폴더가 아니라 드라이브 루트다.
            text = drive + os.sep
    return os.path.normpath(os.path.abspath(text))


def _stays_inside(root_full: str, link_path: str) -> bool:
    """링크가 실제로 루트 안쪽에 머무는가. 해석할 수 없으면 우회로 본다."""
    try:
        real_root = os.path.realpath(root_full)
        real_link = os.path.realpath(link_path)
    except OSError:
        return False
    prefix = real_root.rstrip(os.sep) + os.sep
    return (real_link + os.sep).lower().startswith(prefix.lower())


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & _REPARSE_POINT:
        return True
    return stat.S_ISLNK(info.st_mode)
