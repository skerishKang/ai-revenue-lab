"""The owner's names and plain fixtures keep the underlying trial's safety gate."""
import runpy
from pathlib import Path

def test_plain_adapter_accepts_only_expected_exact_fixtures(monkeypatch):
    path = Path(__file__).with_name("owner_trial_adapter.py")
    adapted = runpy.run_path(str(path))
    trial = adapted["trial"]
    assert trial.WORKERS == {"A":"padiem-cutover-trial-a", "B":"padiem-cutover-trial-b"}
    for body, expected in ((b"trial-a", "A"), (b"trial-b", "B")):
        monkeypatch.setattr(trial, "request", lambda *a, body=body, **kw: (200, {"cache-control":"no-store"}, body))
        assert adapted["plain_http_sample"](trial.HOST) == {"status":200, "identity":expected, "ok":True}
    for body in (b"trial-a ", b"A", b"trial-b\n", b""):
        monkeypatch.setattr(trial, "request", lambda *a, body=body, **kw: (200, {"cache-control":"no-store"}, body))
        assert not adapted["plain_http_sample"](trial.HOST)["ok"]
    assert trial.HOST == "chat-cutover-test.padiem.net"
