"""systemd ExecCondition: fail closed with booleans, never env values."""
import os
from pathlib import Path

DATA = Path("/mnt/d/padiem/chat-com2")
LINUX_DATA = Path("/opt/padiem/chat-com2/data")
AUTH_MODES = {"password", "google", "hybrid"}
MODES = {"mock", "b14"}

#: One line, operator-facing, no configuration values in it. The single-process
#: contract backs the edge-verification semaphore (#6563), the per-upload tus
#: locks (#6604) and the replay connection (#6610).
MULTI_WORKER_REASON = (
    "프로세스 1개 전제 잠금: edge·tus·replay — 교차 프로세스화 전에는 1만 허용"
)

#: Warning only: the computer-use / PC-query lane is disabled while either
#: side lacks the shared value, and that must not stop Chat from starting.
DESKTOP_SECRET_ENV = "CLAW_ENGINE_DESKTOP_SECRET"
DESKTOP_WARNING = (
    "CLAW_ENGINE_DESKTOP_SECRET 없음/32자 미만: 컴퓨터 사용·PC 조회 꺼짐 "
    "(Chat env와 P01 env에 같은 값 필요)"
)


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _workers_at_least_two() -> bool:
    raw = os.environ.get("PADIEM_CHAT_WORKERS", "1").strip()
    return raw.isascii() and raw.isdecimal() and int(raw) >= 2


def _multi_worker_escape() -> bool:
    # The owner's switch; it is off in every deployment today.
    return _flag("PADIEM_CHAT_ALLOW_MULTI_WORKERS", "false")


def ready() -> bool:
    public = os.environ.get("PADIEM_CHAT_PUBLIC_BASE_URL", "")
    data = Path(os.environ.get("PADIEM_CHAT_LOCAL_DATA_DIR", ""))
    return (
        _flag("PADIEM_CHAT_CPYTHON_HOST")
        and not _flag("PADIEM_LOCAL_DEV")
        and public.startswith("https://")
        and not public.endswith("/")
        and data in (DATA, LINUX_DATA)
        and data.is_dir()
        and os.access(data, os.W_OK)
        and _workers_ready()
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


def _workers_ready() -> bool:
    raw = os.environ.get("PADIEM_CHAT_WORKERS", "1").strip()
    if not raw.isascii() or not raw.isdecimal() or int(raw) < 1:
        return False
    if int(raw) == 1:
        return True
    try:
        from app.local_server import validate_worker_configuration
        validate_worker_configuration()
    except (ImportError, OSError, RuntimeError):
        return False
    return True


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


def desktop_tools_warning() -> str | None:
    """A fixed warning line when the shared desktop secret is absent/short."""
    secret = os.environ.get(DESKTOP_SECRET_ENV, "")
    if isinstance(secret, str) and len(secret) >= 32:
        return None
    return DESKTOP_WARNING


if __name__ == "__main__":
    if _workers_at_least_two() and not _multi_worker_escape():
        # ExecCondition exit 2: the launch contract itself is violated, not
        # merely unready. One line, no configuration values.
        print("CHAT_COM2_CONFIG_BLOCKED: " + MULTI_WORKER_REASON)
        raise SystemExit(2)
    valid = ready()
    print("CHAT_COM2_CONFIG_READY=" + ("1" if valid else "0"))
    warning = desktop_tools_warning()
    if warning is not None:
        print("CHAT_COM2_CONFIG_WARNING: " + warning)
    raise SystemExit(0 if valid else 1)
