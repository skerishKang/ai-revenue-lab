"""systemd ExecCondition: fail closed with booleans, never env values."""
import os
from pathlib import Path

DATA = Path("/mnt/d/padiem/chat-com2")
AUTH_MODES = {"password", "google", "hybrid"}
MODES = {"mock", "b14"}


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def ready() -> bool:
    public = os.environ.get("PADIEM_CHAT_PUBLIC_BASE_URL", "")
    return (
        _flag("PADIEM_CHAT_CPYTHON_HOST")
        and not _flag("PADIEM_LOCAL_DEV")
        and public.startswith("https://")
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
    print("CHAT_COM2_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
