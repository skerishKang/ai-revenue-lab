"""Local key-preserving update guards; all public JWKS output stays private."""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

EXPECTED_KID = "auth-4557c4cf0031aae1854a9b8e"
JWKS_URL = "https://auth.padiem.net/.well-known/jwks.json"


def verify_jwks(before, after):
    def keys(value):
        if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
            raise ValueError("public JWKS unavailable")
        entries = value["keys"]
        ids = [entry.get("kid") for entry in entries if isinstance(entry, dict)]
        if any(set(entry) - {"kid", "kty", "crv", "x", "y", "alg", "use", "key_ops"} for entry in entries if isinstance(entry, dict)):
            raise ValueError("unexpected JWKS fields")
        if len(ids) != len(entries) or any(not isinstance(kid, str) for kid in ids) or len(set(ids)) != len(ids) or EXPECTED_KID not in ids:
            raise ValueError("signing key generation mismatch")
        return {entry["kid"]: entry for entry in entries}
    if keys(before) != keys(after):
        raise ValueError("public JWKS changed")
    return True


def deploy_command(config, *, keep_vars):
    if keep_vars is not True:
        raise ValueError("keep-vars is required")
    if config != "apps/padiem-auth/wrangler.toml":
        raise ValueError("unexpected config")
    return ["npx", "--no-install", "wrangler", "deploy", "--config", config, "--keep-vars"]


def main(args):
    mode = args[0]
    if mode == "capture" and len(args) == 2:
        request = urllib.request.Request(JWKS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            value = json.load(response)
        verify_jwks(value, value)
        Path(args[1]).write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        print("signing public key present: PASS")
    elif mode == "compare" and len(args) == 2:
        before = json.loads(Path(args[1]).read_text(encoding="utf-8"))
        request = urllib.request.Request(JWKS_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            after = json.load(response)
        verify_jwks(before, after)
        print("signing public key unchanged: PASS")
    elif mode == "deploy" and len(args) == 2 and args[1] == "--keep-vars":
        command = deploy_command("apps/padiem-auth/wrangler.toml", keep_vars=True)
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise ValueError("invalid update command")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception:
        print("auth update key or command guard refused", file=sys.stderr)
        sys.exit(1)
