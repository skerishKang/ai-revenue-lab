"""#8043: a helper install failure leaves a trace even when the folder is absent.

WriteUserHelperStatus used to return silently when the ProgramData folder did not
exist or was not adoptable, so a helper that never installed left no diagnosable
reason. The fallback records the same secret-free status in the operator's own
temp. This is a source contract test (the shipped artifact is a Windows program);
no other test file is imported.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CS = REPO / "scripts" / "pc_pairing" / "connect-exe" / "PadiemPcConnect.cs"


def _status_function() -> str:
    source = CS.read_text(encoding="utf-8")
    start = source.index("static void WriteUserHelperStatus(")
    end = source.index("static void SayHelperStopped(", start)
    return source[start:end]


def test_helper_status_still_writes_the_adopted_folder_when_it_is_ours():
    fn = _status_function()
    assert "WriteLockedFile(UserHelperStatusPath()" in fn
    assert "FolderAdoptionRefusal(directory, accounts).Length == 0" in fn


def test_helper_status_falls_back_to_operator_temp_when_the_folder_is_absent():
    fn = _status_function()
    assert "Path.GetTempPath()" in fn
    assert "padiem-helper-status.json" in fn
    assert "File.WriteAllBytes(fallback, payload)" in fn
    # The old silent early-return for an absent/unadoptable folder is gone.
    assert "Length > 0)" not in fn
    # Best-effort: the fallback has its own guard so it never throws out.
    assert fn.count("catch (Exception)") >= 2


def test_helper_status_fallback_carries_no_secret():
    fn = _status_function()
    for field in (r'\"status\"', r'\"task\"', r'\"device_id\"',
                  r'\"sha256\"', r'\"user\"', r'\"reason\"'):
        assert field in fn
    assert r'\"secret\"' not in fn
