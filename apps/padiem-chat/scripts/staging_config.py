"""Build a deliberately narrow Wrangler config for the isolated staging Worker."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PRODUCTION_DB = "702bb62b-36f5-41a0-973f-c4f663ee01e6"
STAGING_DB = "e064ac35-6e45-4fd8-9a2c-c3ae6583c964"
PRODUCTION_HOSTS = {"chat.padiem.net", "queue.padiem.net"}
IDENTITY_SERVICE = ("IDENTITY_AUTHORITY_SERVICE", "padiem-control-plane-identity")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


def make_config(database_id, public_origin, queue_origin):
    if not UUID.fullmatch(database_id) or database_id != STAGING_DB or database_id == PRODUCTION_DB:
        raise ValueError("staging database ID required")
    def host(origin):
        u = urlsplit(origin)
        if u.scheme != "https" or not u.hostname or u.hostname in PRODUCTION_HOSTS or u.username or u.password or u.port or u.path or u.query or u.fragment:
            raise ValueError("isolated HTTPS origin required")
        return u.hostname
    chat_host, queue_host = host(public_origin), host(queue_origin)
    if chat_host != "padiem-chat-staging.charliekant.workers.dev":
        raise ValueError("unexpected staging worker origin")
    if queue_host != "queue-staging.padiem.net":
        raise ValueError("unexpected staging queue host")
    return {
        "name": "padiem-chat-staging", "main": "worker.py",
        "compatibility_date": "2026-08-25", "compatibility_flags": ["python_workers"],
        "workers_dev": True, "base_dir": ".b66-worker-src",
        "build": {"command": "uv run python scripts/build_b66_worker_dependencies.py"},
        "assets": {"directory": ".b66-worker-src/static", "binding": "ASSETS"},
        "version_metadata": {"binding": "CF_VERSION_METADATA"},
        # The shared-login staging trial uses the canonical identity authority.
        "services": [{"binding": IDENTITY_SERVICE[0], "service": IDENTITY_SERVICE[1]}],
        "d1_databases": [{"binding": "PADIEM_CHAT_DB", "database_name": "padiem-chat-staging-db", "database_id": database_id}],
        # Start on isolated D1 while Qoder provisions the separate staging queue
        # and secret. Never silently fall back to an operational queue.
        "vars": {"PADIEM_CHAT_PUBLIC_BASE_URL": public_origin, "PC_QUEUE_BACKEND": "d1", "PC_QUEUE_ORIGIN": queue_origin,
                 "PADIEM_CHAT_SHARED_LOGIN_ENABLED": "true", "PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED": "false",
                 "PADIEM_CHAT_SHARED_AUTH_CLIENT_ID": "b62-staging",
                 "PADIEM_CHAT_RUNTIME_MODE": "mock", "PADIEM_CHAT_LIVE_ENABLED": "false"},
        "observability": {"enabled": True, "head_sampling_rate": 1},
    }


if __name__ == "__main__":
    import os
    # Output only a configuration with no credential values.
    Path(sys.argv[1]).write_text(json.dumps(make_config(os.environ["STAGING_CHAT_D1_ID"], os.environ["STAGING_CHAT_ORIGIN"], os.environ["STAGING_QUEUE_ORIGIN"]), indent=2) + "\n", encoding="utf-8")
