import json

from claw_connect.user_helper_update_notice import UpdateNotice


def test_disabled_update_notifies_once_per_version_and_injected_clock(tmp_path):
    status = tmp_path / "helper-status.json"
    shown, marked = [], []
    now = [0]
    notice = UpdateNotice(status, clock=lambda: now[0],
                          notified=lambda: marked[-1] if marked else None,
                          mark=marked.append, show=shown.append)

    def report(version, auto=False, result="available"):
        status.write_text(json.dumps({"status": "installed", "update_result": result,
                                      "auto_update": auto, "update_available_version": version}))

    report("0.4.0", auto=True)
    notice()
    assert not shown
    report("0.4.0")
    now[0] += 30
    notice()
    now[0] += 30
    notice()
    assert shown == marked == ["0.4.0"]
    report("0.5.0")
    now[0] += 30
    notice()
    assert shown == marked == ["0.4.0", "0.5.0"]
