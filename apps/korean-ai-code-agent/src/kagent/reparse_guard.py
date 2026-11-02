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

    정규화된 대상 경로가 허용 루트 밖이면(그 자체로 우회) True다. 루트 자체는
    검사하지 않는다 — 소유자가 허가한 폴더의 위치는 소유자의 결정이다.
    """
    root_full = os.path.abspath(granted_root)
    target_full = os.path.abspath(file_path)
    root_prefix = root_full + os.sep
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
        if _is_reparse(info):
            return True
    return False


def _is_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & _REPARSE_POINT:
        return True
    return stat.S_ISLNK(info.st_mode)
