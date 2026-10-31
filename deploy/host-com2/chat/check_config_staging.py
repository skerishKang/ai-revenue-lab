"""systemd ExecCondition for the staging Chat: booleans only, never env values."""
import os
from pathlib import Path

DATA = Path("/mnt/d/padiem/chat-staging")
AUTH_MODES = {"password", "google", "hybrid"}
MODES = {"mock", "b14"}
QUEUE_ORIGINS = {"http://127.0.0.1:8830", "http://localhost:8830"}
PUBLIC_PREFIX = "https://chat-com2-staging."


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _queue_ready() -> bool:
    origin = os.environ.get("PC_QUEUE_ORIGIN", "").strip().rstrip("/")
    secret_file = os.environ.get("PC_QUEUE_SERVICE_SECRET_FILE", "").strip()
    if (
        os.environ.get("PC_QUEUE_BACKEND", "").strip().lower() != "com2"
        or not _flag("PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP")
        or origin not in QUEUE_ORIGINS
        or os.environ.get("PC_QUEUE_SERVICE_SECRET", "").strip()
        or not secret_file
    ):
        return False
    path = Path(secret_file)
    if not path.is_file() or not os.access(path, os.R_OK):
        return False
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return 16 <= len(secret) <= 256 and all(33 <= ord(ch) <= 126 for ch in secret)


def ready() -> bool:
    public = os.environ.get("PADIEM_CHAT_PUBLIC_BASE_URL", "")
    return (
        _flag("PADIEM_CHAT_CPYTHON_HOST")
        and not _flag("PADIEM_LOCAL_DEV")
        and public.startswith(PUBLIC_PREFIX)
        and not public.endswith("/")
        and os.environ.get("PADIEM_CHAT_LOCAL_DATA_DIR") == str(DATA)
        and DATA.is_dir()
        and os.access(DATA, os.W_OK)
        and os.environ.get("PADIEM_CHAT_AUTH_MODE") in AUTH_MODES
        and _flag("PADIEM_CHAT_COOKIE_SECURE", "true")
        and len(os.environ.get("PADIEM_CHAT_SESSION_SECRET", "")) >= 32
        and os.environ.get("PADIEM_CHAT_RUNTIME_MODE", "mock") in MODES
        and _b14_consistent()
        and _pairs_consistent(
            "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN", "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET"
        )
        and _pairs_consistent(
            "PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN", "PADIEM_CHAT_LOCAL_B66_PDF_SECRET"
        )
        and _flag("PADIEM_CHAT_SHARED_LOGIN_ENABLED")
        and _queue_ready()
    )


def _b14_consistent() -> bool:
    if os.environ.get("PADIEM_CHAT_RUNTIME_MODE", "mock") != "b14":
        return True
    return (
        os.environ.get("B14_UPSTREAM_MODE") == "https"
        and str(os.environ.get("B14_UPSTREAM_URL", "")).startswith("https://")
        and len(os.environ.get("PADIEM_B14_SERVICE_PROOF_SECRET", "")) >= 32
    )


def _pairs_consistent(origin_name: str, secret_name: str) -> bool:
    origin = os.environ.get(origin_name, "").strip()
    secret = os.environ.get(secret_name, "").strip()
    if not origin and not secret:
        return True
    return origin.startswith("https://") and len(secret) >= 32


if __name__ == "__main__":
    valid = ready()
    print("CHAT_STAGING_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
