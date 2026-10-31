"""Adapt the #6422 trial's fixed fixtures to the owner's exact trial names."""
import sys
from pathlib import Path

# Execute only from a clean checkout at the exact main SHA enforced by Trial.
root = Path.cwd()
sys.path.insert(0, str(root / ".github" / "scripts"))
import chat_domain_move_trial as trial

trial.WORKERS = {"A": "padiem-cutover-trial-a", "B": "padiem-cutover-trial-b"}

def plain_http_sample(host):
    try:
        status, headers, raw = trial.request("https://" + host + "/__cutover_trial")
        identity = {b"trial-a": "A", b"trial-b": "B"}.get(raw)
        lower = {key.lower(): value for key, value in headers.items()}
        return {"status": status, "identity": identity,
                "ok": status == 200 and identity is not None and "no-store" in lower.get("cache-control", "")}
    except Exception:
        return {"status": None, "identity": None, "ok": False}

trial.http_sample = plain_http_sample

if __name__ == "__main__":
    raise SystemExit(trial.main())
