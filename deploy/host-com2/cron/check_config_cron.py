"""systemd ExecCondition for the COM2 cron: booleans only, never env values.

The timer's only job is to call `app.local_cron` in the host mode. This gate
answers whether the profile and the process environment actually describe that
host, so a staging timer can never tick against the production data root (or the
8797 queue) by a copied .env file, and a production timer can never tick against
the staging pair.

Printing stays boolean + stable reason code: an env file holds a session secret
and this output lands in the journal.
"""
import os
import sys
from pathlib import Path

FLAGS = {"1", "true", "yes", "on"}
PROFILES = {
    "staging": {
        "data_root": "/mnt/d/padiem/chat-staging",
        "queue_origin": "http://127.0.0.1:8830",
        "public_prefix": "https://chat-com2-staging.",
    },
    "production": {
        "data_root": "/mnt/d/padiem/chat-com2",
        "queue_origin": "http://127.0.0.1:8797",
        "public_prefix": "https://chat.",
    },
}


def _flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in FLAGS


def _text(name):
    return str(os.environ.get(name, "")).strip()


def ready():
    """Return ``(ok, reason)``; the reason is a stable code, never a value."""

    profile = _text("CRON_PROFILE")
    expected = PROFILES.get(profile)
    if expected is None:
        return False, "profile_unknown"
    if not _flag("PADIEM_CHAT_CPYTHON_HOST"):
        return False, "host_flag_off"
    if _flag("PADIEM_LOCAL_DEV"):
        return False, "local_dev_on"
    if _text("PADIEM_CHAT_LOCAL_DATA_DIR") != expected["data_root"]:
        return False, "data_root_mismatch"
    if _text("CRON_EXPECTED_DATA_ROOT") and _text("CRON_EXPECTED_DATA_ROOT") != expected["data_root"]:
        return False, "unit_data_root_mismatch"
    root = Path(expected["data_root"])
    if not root.is_dir() or not os.access(root, os.W_OK):
        return False, "data_root_unusable"
    if not _flag("PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED"):
        return False, "automation_scheduler_disabled"
    public = _text("PADIEM_CHAT_PUBLIC_BASE_URL")
    if not public.startswith(expected["public_prefix"]) or public.endswith("/"):
        return False, "public_origin_mismatch"
    if len(_text("PADIEM_CHAT_SESSION_SECRET")) < 32:
        return False, "session_secret_short"
    queue = _text("PC_QUEUE_ORIGIN").rstrip("/")
    if queue != expected["queue_origin"]:
        return False, "queue_origin_mismatch"
    if _text("CRON_EXPECTED_QUEUE_ORIGIN") and _text("CRON_EXPECTED_QUEUE_ORIGIN").rstrip(
        "/"
    ) != expected["queue_origin"]:
        return False, "unit_queue_origin_mismatch"
    return True, "ready"


if __name__ == "__main__":
    ok, reason = ready()
    print(f"CRON_CONFIG_READY={'1' if ok else '0'} reason={reason}")
    sys.exit(0 if ok else 1)
