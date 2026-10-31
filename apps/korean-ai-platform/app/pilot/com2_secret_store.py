"""#2107 the credential plane the Owner maintains on this host, by NAME.

The Owner's decision is that a new Provider's key is typed on COM2 as a name and
a value, with no duplicate Cloudflare Secret and no new secret engine. This
module is the write side of the door that already reads: `app.local_runtime`
resolves ``os.environ[NAME]`` then ``$B14_SECRET_DIR/NAME`` and refuses a file
that group or other can read, so a value written here is read back by the exact
code path a Provider already uses.

Nothing in this module returns, logs or renders a value. The only facts about a
value it reports are whether one is present and whether it was rejected for a
shape reason — never its content, length, prefix or hash.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from app.local_runtime import is_binding_name, secret_dir

MAX_VALUE_BYTES = 4096

# Value-free outcome codes. Each one names a cause the operator can act on
# without the response carrying anything about the credential itself.
OK = ""
NOT_CONFIGURED = "secret_dir_not_configured"
NAME_INVALID = "secret_name_invalid"
NAME_NOT_DECLARED = "secret_name_not_in_registry"
VALUE_EMPTY = "value_empty"
VALUE_PLACEHOLDER = "value_placeholder"
VALUE_TOO_LONG = "value_too_long"
CLOUDFLARE_RESERVED = "name_declared_as_cloudflare_binding"
DIR_NOT_PRIVATE = "secret_dir_not_private"
DIR_NOT_WRITABLE = "secret_dir_not_writable"
NOT_PRESENT = "secret_not_present"
IO_FAILED = "secret_write_failed"


def _declared_names() -> dict[str, list[str]]:
    """Credential name -> provider ids that declare it, from the one registry."""
    from app.pilot.model_registry_file import read_registry

    declared: dict[str, list[str]] = {}
    try:
        providers = read_registry()["providers"]
    except Exception:
        # An unreadable registry is reported by the registry's own startup
        # guard; here it simply means nothing can be claimed as declared.
        return {}
    for provider_id, entry in providers.items():
        if entry.get("credential_source") != "platform_secret":
            continue
        binding = entry.get("credential_binding_name") or ""
        if binding:
            declared.setdefault(binding, []).append(provider_id)
    return declared


def _model_rows() -> list[dict[str, Any]]:
    from app.pilot.model_registry_file import read_registry

    try:
        return list(read_registry()["models"])
    except Exception:
        return []


def _cloudflare_declared_names() -> frozenset[str]:
    """Names the Worker deployment already binds in wrangler.toml.

    Reusing one of these for a different Provider would give one name two values
    on two hosts, so a fresh Provider must take a fresh name. The file is not
    authority on a host that never deploys to Cloudflare, so an absent file
    simply reserves nothing.
    """
    path = Path(__file__).resolve().parents[2] / "wrangler.toml"
    if not path.is_file():
        return frozenset()
    import tomllib

    try:
        with path.open("rb") as handle:
            declared = tomllib.load(handle)
    except Exception:
        return frozenset()
    return frozenset(
        entry.get("binding", "")
        for entry in declared.get("secrets_store_secrets", [])
        if entry.get("binding")
    )


def validate_name(name: str, *, for_new_provider: bool = False) -> str:
    """Return a value-free reason this name may not be written here."""
    if not is_binding_name(name):
        return NAME_INVALID
    if for_new_provider and name in _cloudflare_declared_names():
        return CLOUDFLARE_RESERVED
    return OK


def usage(name: str) -> dict[str, Any]:
    """Which Providers and models a name carries, and whether a value is there."""
    providers = sorted(set(_declared_names().get(name, [])))
    rows = [row for row in _model_rows() if row["provider_id"] in providers]
    return {
        "name": name,
        "declared_providers": providers,
        "models": sorted(row["id"] for row in rows),
        "enabled_models": sorted(row["id"] for row in rows if row.get("enabled")),
        "present": bool(read_state(name)["present"]),
    }


def read_state(name: str) -> dict[str, Any]:
    """Whether a usable value exists under ``name`` — never the value itself."""
    directory = secret_dir()
    if directory is None:
        return {"present": False, "state": "not_configured", "code": NOT_CONFIGURED}
    path = directory / name
    if not path.is_file():
        env_value = os.environ.get(name, "")
        if env_value:
            return {"present": True, "state": "env", "code": OK}
        return {"present": False, "state": "missing", "code": NOT_PRESENT}
    if not _is_private(path):
        # The reader refuses this file too, so a value that exists on disk is
        # not a credential the application can use. Report it, do not hide it.
        return {"present": False, "state": "rejected_mode", "code": DIR_NOT_PRIVATE}
    return {"present": True, "state": "file", "code": OK}


def _is_private(path: Path) -> bool:
    if os.name != "posix":
        return True
    try:
        return not (path.stat().st_mode & 0o077)
    except OSError:
        return False


def list_rows() -> list[dict[str, Any]]:
    """Every name the Owner can act on: declared by the registry or on disk.

    A file with no Provider behind it stays visible as an unregistered row,
    which is what lets the Owner see an orphan left by a removed Provider.
    """
    directory = secret_dir()
    names = set(_declared_names())
    if directory is not None and directory.is_dir():
        for entry in directory.iterdir():
            if entry.is_file() and is_binding_name(entry.name):
                names.add(entry.name)
    rows = [usage(name) for name in sorted(names)]
    for row in rows:
        row.update(read_state(row["name"]))
    return rows


def find(name: str) -> dict[str, Any] | None:
    if not is_binding_name(name):
        return None
    row = usage(name)
    row.update(read_state(name))
    return row


def write(name: str, value: str) -> str:
    """Store ``value`` under ``name``. Returns OK or a value-free reason."""
    if is_binding_name(name) is False:
        return NAME_INVALID
    directory = secret_dir()
    if directory is None:
        return NOT_CONFIGURED
    if not value or not value.strip():
        return VALUE_EMPTY
    encoded = value.strip().encode("utf-8")
    if len(encoded) > MAX_VALUE_BYTES:
        return VALUE_TOO_LONG
    if _looks_like_placeholder(value):
        return VALUE_PLACEHOLDER
    if not _prepare_directory(directory):
        return DIR_NOT_WRITABLE
    # Written 0600 from the first byte and moved in with one rename, so there is
    # no moment where a half-written credential is the live file.
    handle, temp_path = tempfile.mkstemp(dir=directory, prefix=f".{name}.")
    try:
        with os.fdopen(handle, "wb") as secret_file:
            secret_file.write(encoded)
            secret_file.flush()
            os.fsync(secret_file.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, directory / name)
    except OSError:
        _discard(temp_path)
        return IO_FAILED
    return OK


def _discard(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _prepare_directory(directory: Path) -> bool:
    """The host must own a private directory; this never relaxes it."""
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return False
    if os.name == "posix":
        try:
            if directory.stat().st_mode & 0o077:
                return False
        except OSError:
            return False
    return os.access(directory, os.W_OK | os.X_OK)


def delete(name: str) -> str:
    directory = secret_dir()
    if directory is None:
        return NOT_CONFIGURED
    if not is_binding_name(name):
        return NAME_INVALID
    path = directory / name
    if not path.is_file():
        return NOT_PRESENT
    try:
        path.unlink()
    except OSError:
        return IO_FAILED
    return OK


def _looks_like_placeholder(value: str) -> bool:
    from app.pilot.platform_secrets import looks_like_placeholder

    return looks_like_placeholder(value)
