"""#261105: a refusal names the leg it happened on, not one guess for all.

On 2026-11-05 a node_ref validation refusal on two PCs reached the Owner as
"등록된 폴더 기준 상대경로만 허용", so a path theory and then a permission
theory were investigated before the executor line named the real cause. The
hint now follows the closed stage: a request refused here, a PC-side read
failure and a result that never came back read differently, and only the path
stages keep the registered-root sentence.
"""

from app.claw_pc_query_step_driver import (
    PC_FILE_ERROR_PREFIX,
    _pc_read_marker,
    _pc_refusal,
    _pc_refusal_hint,
)


def test_a_local_validation_refusal_is_not_described_as_a_path_rule():
    hint = _pc_refusal("pc_file_read_failed_refused_local")["hint"]
    assert "검증" in hint
    assert "등록된 폴더" not in hint


def test_a_pc_side_read_failure_is_not_described_as_a_path_rule():
    hint = _pc_refusal("pc_file_read_failed")["hint"]
    assert "PC" in hint
    assert "등록된 폴더" not in hint
    assert hint != _pc_refusal("pc_file_read_failed_refused_local")["hint"]


def test_a_result_that_never_came_back_reads_as_a_result_lookup_failure():
    for stage in (
        "pc_files_output_missing",
        "pc_files_result_mismatch",
        "pc_files_dispatch_missing",
        "pc_files_dispatch_unavailable",
    ):
        hint = _pc_refusal(stage)["hint"]
        assert "결과" in hint
        assert "등록된 폴더" not in hint


def test_the_registered_root_sentence_survives_only_for_path_stages():
    for stage in ("pc_files_path_invalid", "pc_file_arguments_invalid"):
        assert "등록된 폴더" in _pc_refusal(stage)["hint"]
    for stage in ("pc_files_execution_failed", "pc_query_internal_error", None):
        assert "등록된 폴더" not in _pc_refusal(stage)["hint"]
    assert len({
        _pc_refusal_hint(stage) for stage in (
            "pc_file_read_failed_refused_local",
            "pc_file_read_failed",
            "pc_files_output_missing",
            "pc_files_path_invalid",
            "pc_files_execution_failed",
        )
    }) == 5


def test_the_refused_request_marker_keeps_the_read_lane_vocabulary():
    # The executor's new body is still one bounded marker the engine maps; the
    # PC-side failure keeps the value it always had.
    assert _pc_read_marker(PC_FILE_ERROR_PREFIX + "read_failed_refused_local") == (
        "read_failed_refused_local")
    assert _pc_read_marker(PC_FILE_ERROR_PREFIX + "read_failed") == "read_failed"
    assert _pc_read_marker("file text") is None
    assert _pc_read_marker(PC_FILE_ERROR_PREFIX + "x" * 80) is None
