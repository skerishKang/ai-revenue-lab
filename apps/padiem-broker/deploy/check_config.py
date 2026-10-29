"""systemd ExecCondition: fail closed with booleans, never env or secret values."""
import os
from pathlib import Path

DATA = Path("/mnt/d/padiem/broker")
MIN_SECRET = 32


def _value_or_none(inline: str, file_env: str) -> str | None:
    inline_value = os.environ.get(inline, "").strip()
    if inline_value:
        return inline_value
    path = os.environ.get(file_env, "").strip()
    if not path:
        return None
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def ready() -> bool:
    proof = _value_or_none(
        "PADIEM_BROKER_RPC_INGRESS_SECRET", "PADIEM_BROKER_RPC_INGRESS_SECRET_FILE"
    )
    pepper = _value_or_none("LOCAL_AGENT_BROKER_PEPPER", "LOCAL_AGENT_BROKER_PEPPER_FILE")
    return (
        proof is not None and len(proof) >= MIN_SECRET
        and pepper is not None and len(pepper) >= MIN_SECRET
        and bool(os.environ.get("LOCAL_AGENT_BROKER_AUTHORITY_REF", "").strip())
        and os.environ.get("PADIEM_BROKER_DB_PATH") == str(DATA / "broker.sqlite3")
        and DATA.is_dir() and os.access(DATA, os.W_OK)
    )


if __name__ == "__main__":
    valid = ready()
    print("BROKER_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
