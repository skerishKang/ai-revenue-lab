"""Offline tests for the COM2 read-only diagnostic."""
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

FILE = Path(__file__).resolve().parents[1] / "com2_remote_diagnose.py"
spec = importlib.util.spec_from_file_location("com2_remote_diagnose", FILE)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)
CFG = {"com2_host":"host", "com2_ssh_user":"reader", "com2_ssh_key":"key", "com2_ssh_port":22}

def test_fixed_collector_compiles_and_is_read_only():
    compile(diag.LINUX, "<collector>", "exec")
    program = diag.remote_command()
    assert "wsl.exe -d Ubuntu -e python3" in program
    assert "Get-ScheduledTaskInfo" in program
    for forbidden in ("Restart-Service", "Start-Service", "Set-Service", "runcommand", "Set-Content"):
        assert forbidden not in program
    assert "journalctl" not in program  # Linux program is encoded in transit

def test_recovery_ignores_obsolete_tunnel_noise_and_redacts(tmp_path):
    p = tmp_path / "recovery.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"ts":"2026-10-30T01:00:00Z","class":"tunnel_listener_down","executed":True,"recovery_ok":"no"},
        {"ts":"2026-10-30T02:00:00Z","class":"mesh_down","executed":True,"recovery_ok":"yes","secret":"DO_NOT_PRINT"},
        {"ts":"2026-10-30T03:00:00Z","class":"mesh_down","executed":False}]))
    assert diag.recovery(str(p)) == [{"at":"2026-10-30T02:00:00Z","recovery_ok":"yes"}]
    assert diag.recovery(str(tmp_path / "missing")) == "unavailable"

def test_ssh_uses_bounded_identity_and_only_fixed_stdin():
    calls = []
    def runner(args, **kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"linux":{"units":{"x":"active"}}}))
    got = diag.diagnose(CFG, runner)
    assert got["remote"]["linux"]["units"]["x"] == "active"
    args, opts = calls[0]
    assert args[0] == "ssh" and "-i" in args and "reader@host" in args
    assert "BatchMode=yes" in args and opts["timeout"] <= 90
    import base64, re
    encoded = re.search(r"FromBase64String\(\'([^\']+)\'\)", opts["input"]).group(1)
    assert base64.b64decode(encoded).decode() == diag.remote_command()
    assert "runcommand" not in " ".join(args)

def test_timeout_auth_and_bad_json_are_unavailable():
    def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("ssh", 75)
    assert diag.diagnose(CFG, timeout)["remote"] == "unavailable"
    for result in (SimpleNamespace(returncode=255, stdout="secret"),
                   SimpleNamespace(returncode=0, stdout="not-json")):
        assert diag.diagnose(CFG, lambda *a, **kw: result)["remote"] == "unavailable"


def test_linux_collector_projects_sample_without_secrets(monkeypatch, capsys):
    import builtins
    import io
    import shutil
    import urllib.request
    real_open = builtins.open
    def open_sample(path, *args, **kwargs):
        if str(path).endswith("queue.env"):
            return io.StringIO("SECRET=do-not-print\nMESH_QUEUE_REQUEST_LOG=refusals\n")
        if str(path).endswith("ledger.jsonl"):
            return io.StringIO('{"at":"2026-10-30T01:02:03Z","key_id":"do-not-print"}\n')
        return real_open(path, *args, **kwargs)
    def fake_run(args, **kwargs):
        if args[0] == "systemctl":
            if "--property=LoadState" in args: out = "loaded\n"
            elif "--property=ActiveState" in args: out = "active\n"
            else: out = "2\n"
        elif "-p" in args: out = "error one\nerror two\n"
        elif "padiem-oracle-mesh-executor.service" in args:
            out = "oracle-mesh-executor channel refusal: refused leg=queue\noracle-mesh-executor channel refusal: refused leg=chat\n"
        else:
            out = "MESH_QUEUE_REQUEST path=x rpc=none status=403 ms=2 proof=bad\n"
        return SimpleNamespace(returncode=0, stdout=out, stderr="")
    class Response(io.BytesIO):
        pass
    monkeypatch.setattr(builtins, "open", open_sample)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response(b'{"pending_unclaimed":1,"pending_claimed":2,"received":3,"secret":"do-not-print"}'))
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(free=123))
    exec(diag.LINUX, {})
    output = capsys.readouterr().out
    obj = json.loads(output)
    assert obj["queue_log_mode"] == "refusals"
    assert obj["executor_refusals"] == {"queue":1,"chat":1,"unknown":0}
    assert obj["queue_refusals"] == 1 and obj["queue_health"]["received"] == 3
    assert obj["offsite_latest"] == "2026-10-30T01:02:03Z"
    assert "do-not-print" not in output
