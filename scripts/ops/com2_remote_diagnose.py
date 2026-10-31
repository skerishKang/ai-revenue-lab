#!/usr/bin/env python3
"""Read-only COM2 diagnostics over the existing COM1 health-monitor SSH identity.

Usage: python scripts/ops/com2_remote_diagnose.py --config C:/Users/.../Padiem/com2-mesh-config.json
Each signal is bounded, projected to an allowlist, and missing evidence is unavailable.
No remote files, services or settings are changed. The window is the last 24 hours.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zlib
from datetime import datetime, timezone

UNAVAILABLE = "unavailable"

# This program runs inside WSL via the existing Windows SSH endpoint. It never
# outputs journal lines, env contents, tokens, request data, or backup manifests.
LINUX = r'''
import json, os, re, shutil, subprocess, urllib.request
U = "unavailable"
journal_warnings = set()
def run(args, timeout=4):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        if args[0] == "journalctl" and p.stderr:
            journal_warnings.add("truncated_file" if "is truncated, ignoring file" in p.stderr else "other_warning")
            return None
        if args[0] == "journalctl" and p.returncode != 0: journal_warnings.add("unavailable")
        return p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        if args[0] == "journalctl": journal_warnings.add("unavailable")
        return None
def state(unit):
    loaded = prop(unit, "LoadState")
    active = prop(unit, "ActiveState")
    return active if loaded == "loaded" and active in ("active", "inactive", "failed", "activating", "deactivating") else U
def prop(unit, name):
    s = run(["systemctl","show",unit,"--property="+name,"--value"])
    return s.strip() if s and s.strip() else U
def journal(unit, priority=None):
    a = ["journalctl","--no-pager","-u",unit,"--since","24 hours ago","-o","cat"]
    if priority: a += ["-p", priority]
    return run(a, 8)
units = ["padiem-mesh-queue.service","padiem-oracle-mesh-executor.service",
         "cloudflared-padiem.service","padiem-meshcentral.service",
         "padiem-mesh-health.timer","padiem-mesh-queue-health.timer",
         "padiem-mesh-recovery.timer", "padiem-offsite-backup.timer"]
out = {"units": {u: state(u) for u in units}, "error_window": "24h"}
for u in units[:4]:
    j = journal(u, "err")
    out.setdefault("errors", {})[u] = len(j.splitlines()) if j is not None else U
out["executor_restarts"] = prop(units[1], "NRestarts")
j = journal(units[1])
out["executor_refusals"] = U if j is None else {
    leg: sum("oracle-mesh-executor channel refusal:" in line and (("leg="+leg) in line if leg != "unknown" else not re.search(r"\bleg=(?:chat|queue)\b", line)) for line in j.splitlines())
    for leg in ("queue","chat","unknown")}
j = journal(units[0])
out["queue_refusals"] = U if j is None else sum(
    bool(re.search(r"MESH_QUEUE_REQUEST .*status=[45][0-9][0-9](?: |$)", line))
    for line in j.splitlines())
out["queue_log_mode"] = U
try:
    with open("/opt/padiem/mesh-queue/queue.env", encoding="utf-8") as f:
        for line in f:
            m = re.fullmatch(r"\s*MESH_QUEUE_REQUEST_LOG\s*=\s*['\"]?(off|all|refusals)['\"]?\s*", line.strip())
            if m: out["queue_log_mode"] = m.group(1)
except OSError: pass
try:
    with urllib.request.urlopen("http://127.0.0.1:8797/health", timeout=3) as response:
        h = json.load(response)
    out["queue_health"] = {k: h[k] if type(h.get(k)) is int and h[k] >= 0 else U
        for k in ("pending_unclaimed","pending_claimed","received")}
except Exception: out["queue_health"] = U
try: out["wsl_free_bytes"] = shutil.disk_usage("/").free
except OSError: out["wsl_free_bytes"] = U
out["offsite_latest"] = U
try:
    with open("/var/lib/padiem-offsite-backup/ledger.jsonl", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    times = [x.get("at") for x in records if isinstance(x, dict) and isinstance(x.get("at"), str)
             and re.fullmatch(r"[0-9T:.+Z-]{10,40}", x["at"])]
    if times: out["offsite_latest"] = max(times)
    out["offsite_by_service"] = {service: max((x["at"] for x in records if isinstance(x, dict) and x.get("service") == service and isinstance(x.get("at"), str) and re.fullmatch(r"[0-9T:.+Z-]{10,40}", x["at"])), default=U) for service in ("chat", "queue", "broker", "d1-chat", "d1-engine")}
except (OSError, ValueError): pass
out["journal_integrity"] = sorted(journal_warnings) if journal_warnings else "no_warning"
print(json.dumps(out, separators=(",",":")))
'''

def remote_command() -> str:
    # Send the fixed PowerShell program over stdin to avoid the Windows command-line limit.
    packed = zlib.compress(LINUX.encode())
    # No quote characters or spaces: WSL command-line translation must not
    # remove quotes from Python's -c argument on Windows OpenSSH.
    linux = "exec(__import__(chr(122)+chr(108)+chr(105)+chr(98)).decompress((0x" + packed.hex() + ").to_bytes(" + str(len(packed)) + ")))"
    ps = r"""
$ErrorActionPreference='Stop'
$r=@{ disks=@{}; d1_sync='unavailable'; legacy_meshcentral='unavailable'; linux='unavailable' }
foreach ($d in @('C','D')) {
  try { $v=Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='"+$d+":'") -ErrorAction Stop
    if ($v -and $null -ne $v.FreeSpace) { $r.disks[$d]=[long]$v.FreeSpace } else { $r.disks[$d]='unavailable' }
  } catch { $r.disks[$d]='unavailable' }
}
try { $t=Get-ScheduledTaskInfo -TaskName 'PADIEM-COM2-D1-R2-Sync' -ErrorAction Stop
  if ($t.LastRunTime.Year -gt 2000) { $r.d1_sync=@{last_run=$t.LastRunTime.ToUniversalTime().ToString('o'); result=[int64]$t.LastTaskResult} }
} catch {}
try { $s=Get-Service -Name 'MeshCentral' -ErrorAction Stop
  if ($s) {
    $r.legacy_meshcentral=@{state=[string]$s.Status; start_mode=[string]$s.StartType; crashes_24h='unavailable'; classification='informational'}
    try { $events=Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Service Control Manager'; Id=7031,7034; StartTime=(Get-Date).AddHours(-24)} -ErrorAction Stop
      $r.legacy_meshcentral.crashes_24h=@($events | Where-Object { $_.Message -match 'MeshCentral' }).Count
    } catch { if ($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound') { $r.legacy_meshcentral.crashes_24h=0 } }
  }
} catch {}
try {
  $p = '__LINUX__'
  $raw = & wsl.exe -d Ubuntu -u root -e python3 -c $p 2>$null
  if ($LASTEXITCODE -eq 0) { $r.linux = ($raw | ConvertFrom-Json -ErrorAction Stop) }
} catch {}
$r | ConvertTo-Json -Depth 9 -Compress
""".replace("__LINUX__", linux)
    return ps

def recovery(path: str | None):
    if not path: return UNAVAILABLE
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError): return UNAVAILABLE
    records = []
    for line in lines[-5000:]:
        try: x = json.loads(line)
        except ValueError: continue
        if not isinstance(x, dict) or x.get("class") == "tunnel_listener_down": continue
        if str(x.get("executed", "")).lower() not in ("true", "1"): continue
        ts = x.get("ts")
        if not isinstance(ts, str) or not re.fullmatch(r"[0-9T:.+Z-]{10,40}", ts): continue
        records.append({"at":ts, "recovery_ok":str(x.get("recovery_ok","unknown")) if str(x.get("recovery_ok","unknown")) in ("yes","no","unknown") else "unknown"})
    return records[-10:]

def diagnose(config, runner=subprocess.run):
    result = {"schema":"com2-diagnosis-v1", "observed_at":datetime.now(timezone.utc).isoformat(), "remote":UNAVAILABLE,
              "recovery_history":recovery(config.get("recovery_log"))}
    try:
        timeout = min(max(int(config.get("ssh_timeout_seconds",15)), 10), 90)
        # Multiple independently bounded WSL probes need an overall ceiling.
        timeout = max(timeout, 75)
        args = ["ssh", "-F", "none", "-o", "StrictHostKeyChecking=no",
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
                "-p", str(int(config.get("com2_ssh_port",22))), "-i", config["com2_ssh_key"],
                config["com2_ssh_user"]+"@"+config["com2_host"],
                "powershell.exe -NoProfile -NonInteractive -Command -"]
        payload = base64.b64encode(remote_command().encode("utf-8")).decode("ascii")
        invocation = "Invoke-Expression ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(\'" + payload + "\')))\n"
        p = runner(args, input=invocation, capture_output=True, text=True, timeout=timeout)
        if p.returncode == 0:
            x = json.loads(p.stdout)
            if isinstance(x, dict): result["remote"] = x
    except (KeyError, ValueError, OSError, subprocess.TimeoutExpired): pass
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=os.path.expandvars(r"%USERPROFILE%\Padiem\com2-mesh-config.json"))
    ap.add_argument("--json", action="store_true", help="JSON only")
    args = ap.parse_args()
    try:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
        result = diagnose(cfg)
    except (OSError, ValueError): result = {"schema":"com2-diagnosis-v1","observed_at":datetime.now(timezone.utc).isoformat(),"remote":UNAVAILABLE,"recovery_history":UNAVAILABLE}
    if not args.json:
        print("observed_at | " + result["observed_at"])
        print("SIGNAL | VALUE")
        print("-------|------")
        remote = result["remote"]
        if isinstance(remote, dict):
            def rows(prefix, value):
                if isinstance(value, dict):
                    for key, item in value.items(): rows(f"{prefix}.{key}" if prefix else key, item)
                else: print(f"{prefix} | {json.dumps(value, ensure_ascii=False)}")
            rows("", remote)
        else: print("remote | unavailable")
        print("recovery_history | " + json.dumps(result["recovery_history"], ensure_ascii=False))
        print("\nJSON:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if isinstance(result["remote"], dict) and isinstance(result["remote"].get("linux"), dict) else 2

if __name__ == "__main__": sys.exit(main())
