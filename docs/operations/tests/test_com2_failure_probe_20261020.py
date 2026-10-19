"""Temporary, deliberately failing COM2 status E2E probe. Never merge."""

def test_com2_failure_reports_failed_commit_status():
    assert False, 'expected COM2 policy failure status during isolated PR test'
