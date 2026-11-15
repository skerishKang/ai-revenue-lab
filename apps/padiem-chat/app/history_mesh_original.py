"""메시 원본 상한 (#7790 R6 세 번째 구역 중 하나).

`app/history.py`에서 위치만 옮긴 원본 상한 판단과 배포 행 상한이다. 동작·응답
형식·DB 쿼리 결과는 변하지 않으며, 기존 경로는 `app/history.py`가 이 이름들을
다시 내보낸다.
"""
from __future__ import annotations

import re
from typing import Any

#: #4139 mesh result originals share the private full-context R2 store with
#: chat/model full texts. The bound is the result wire envelope the server
#: already accepted and verified (6 MB), not a new trial number: the bytes are
#: already in memory, so storing adds no second buffer beyond the one UTF-8
#: encode. R2 keys stay server-derived (conversation + deterministic result
#: id); a browser can never choose an object key.
ORACLE_MESH_ORIGINAL_MAX_BYTES = 6_000_000


def _oracle_mesh_original_max_bytes(
    row: dict[str, Any], command_max_bytes: int | None = ORACLE_MESH_ORIGINAL_MAX_BYTES,
) -> int | None:
    # The persisted server dispatch owns this distinction, never a store-call
    # argument or model value. Other reads retain the 6MB guard; only command
    # results can use the host-configured limit.
    if row.get("kind") == "read" and row.get("root_ref") == "pc_files_read":
        # #5882 A: the PC read lane has no product store cap of its own. These
        # bytes were verified against the dispatch pin (size + digest) just
        # above, and what actually bounds them is the connector's read
        # envelope — a smaller store number only refused a read that had
        # already succeeded. A file larger than one answer is paged by the
        # Engine from its first range instead.
        return None
    if row.get("kind") == "command":
        return command_max_bytes
    return ORACLE_MESH_ORIGINAL_MAX_BYTES


#: #4139 dispatch row bounds. Each number is the ceiling of the thing it
#: describes, not a safety guess:
#: * a reference keeps the bound this table has always used;
#: * a Windows path is bounded by the documented maximum path length
#:   (32,767 characters with the extended-length prefix; Microsoft, "Maximum
#:   Path Length Limitation"), because a Korean or long PC path is ordinary
#:   input and the former 1,024-character bound rejected it;
#: * the row as a whole is bounded by Cloudflare D1's documented
#:   "Maximum string, BLOB or table row size: 2,000,000 bytes". A command carries
#:   no product length rule: it travels as a bound parameter, so the 100,000-byte
#:   SQL-statement ceiling does not apply to it, and the row it is written into
#:   is the storage boundary. The execution boundary is separate and belongs to
#:   the host (the command port refuses a wrapped command over one argv element),
#:   not to this table.
MAX_MESH_REFERENCE_CHARS = 1024
MAX_MESH_PATH_CHARS = 32_767
MAX_MESH_ROW_BYTES = 2_000_000
_MESH_PATH_FIELDS = frozenset({"path_relative", "file_path"})
#: #4139 terminal/file result ids: the deterministic `msg_ltr_<40hex>` base
#: from the result projection, plus the conversation splitter suffix.
_MESH_RESULT_MESSAGE_ID_RE = re.compile(r"msg_ltr_[0-9a-f]{40}(_p[0-9]+)?")
