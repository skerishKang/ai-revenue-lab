"""systemd ExecCondition: fail closed with booleans, never env values."""
import os
from pathlib import Path


def ready():
    root = Path("/mnt/d/padiem/file-lane")
    return (len(os.environ.get("FILE_LANE_TICKET_SECRET", "")) >= 32
            and os.environ.get("FILE_LANE_ROOT") == str(root)
            and os.environ.get("FILE_LANE_HOST") == "127.0.0.1"
            and os.environ.get("FILE_LANE_PORT") == "8788"
            and root.is_dir() and os.access(root, os.W_OK))


if __name__ == "__main__":
    valid = ready()
    print("FILE_LANE_CONFIG_READY=" + ("1" if valid else "0"))
    raise SystemExit(0 if valid else 1)
