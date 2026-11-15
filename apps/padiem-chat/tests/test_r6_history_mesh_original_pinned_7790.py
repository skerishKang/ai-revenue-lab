"""R6 세 번째 구역 회귀 — 메시 원본 상한과 고정 열 판정이 `history.py` 재수출로 같은 결과를 낸다 (#7790).

소스 문자열이 아니라 실제 호출로 검증한다. 지역·모의만 사용한다(운영 DB·로그인·답변 생성 없음).
"""
from __future__ import annotations

from app import history as history_entry
from app import history_mesh_original as mesh_module
from app import history_pinned as pinned_module


def test_reexport_names_are_the_same_objects() -> None:
    for name in (
        "ORACLE_MESH_ORIGINAL_MAX_BYTES",
        "MAX_MESH_REFERENCE_CHARS",
        "MAX_MESH_PATH_CHARS",
        "MAX_MESH_ROW_BYTES",
        "_oracle_mesh_original_max_bytes",
        "_MESH_PATH_FIELDS",
        "_MESH_RESULT_MESSAGE_ID_RE",
    ):
        assert getattr(history_entry, name) is getattr(mesh_module, name), name
    for name in ("_PINNED_COLUMN_MISSING", "_pinned_column_missing"):
        assert getattr(history_entry, name) is getattr(pinned_module, name), name


def test_oracle_mesh_original_max_bytes_direct_call() -> None:
    assert history_entry._oracle_mesh_original_max_bytes({"kind": "command"}, None) is None
    assert history_entry._oracle_mesh_original_max_bytes({"kind": "command"}, 8_000_000) == 8_000_000
    assert history_entry._oracle_mesh_original_max_bytes({"kind": "read", "root_ref": "pc_files_read"}, None) is None
    assert history_entry._oracle_mesh_original_max_bytes({"kind": "read", "root_ref": "other"}, None) == 6_000_000
    assert history_entry._oracle_mesh_original_max_bytes({"kind": "other"}, None) == 6_000_000
    assert mesh_module._oracle_mesh_original_max_bytes({"kind": "command"}, 1) == 1


def test_mesh_row_bounds_and_message_pattern() -> None:
    assert history_entry.MAX_MESH_REFERENCE_CHARS == 1024
    assert history_entry.MAX_MESH_PATH_CHARS == 32_767
    assert history_entry.MAX_MESH_ROW_BYTES == 2_000_000
    assert history_entry._MESH_PATH_FIELDS == frozenset({"path_relative", "file_path"})
    assert history_entry._MESH_RESULT_MESSAGE_ID_RE.fullmatch("msg_ltr_" + "a" * 40) is not None
    assert history_entry._MESH_RESULT_MESSAGE_ID_RE.fullmatch("msg_ltr_" + "a" * 40 + "_p3") is not None
    assert history_entry._MESH_RESULT_MESSAGE_ID_RE.fullmatch("msg_ltr_short") is None


def test_pinned_column_missing_direct_call() -> None:
    assert history_entry._pinned_column_missing(Exception("no such column: pinned")) is True
    assert history_entry._pinned_column_missing(Exception("no such column: c.pinned")) is True
    assert history_entry._pinned_column_missing(Exception("no such column: other")) is False
    assert history_entry._pinned_column_missing(Exception("some other error")) is False
    assert pinned_module._pinned_column_missing(Exception("no such column: pinned")) is True
