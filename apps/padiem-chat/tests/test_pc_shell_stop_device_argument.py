"""pc_shell_stop advertises ``device`` in its schema, so passing it must be accepted.

Live report (2026-11-07): an external client passed device="PADIEM-COMMAND-" (the
display name pc_devices returned) to pc_shell_stop and got HTTP 400; the same call
without device succeeded.
"""
from app.mcp_gateway_shell import (
    PC_SHELL_STOP_PROPERTIES,
    normalize_pc_shell_stop_arguments,
    validate_pc_shell_stop_arguments,
)

JOB = "dsp_9162dd2fe8d7422db54ce52839b6365b"


def test_schema_advertises_device():
    assert "device" in PC_SHELL_STOP_PROPERTIES


def test_stop_accepts_display_name_device():
    assert validate_pc_shell_stop_arguments({"job_id": JOB, "device": "PADIEM-COMMAND-"})
    assert normalize_pc_shell_stop_arguments({"job_id": JOB, "device": "iD62t1"}) == {"job_id": JOB}


def test_stop_without_device_still_works():
    assert validate_pc_shell_stop_arguments({"job_id": JOB})


def test_stop_rejects_unknown_keys_and_bad_values():
    assert not validate_pc_shell_stop_arguments({"job_id": JOB, "extra": 1})
    assert not validate_pc_shell_stop_arguments({"job_id": JOB, "device": 5})
    assert not validate_pc_shell_stop_arguments({"device": "iD62t1"})
    assert not validate_pc_shell_stop_arguments({"job_id": "short"})
