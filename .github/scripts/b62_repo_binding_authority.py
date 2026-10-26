"""Repository binding inventory, name/type-only diff and exact readback."""
from __future__ import annotations

import json
from uuid import UUID


class BindingAuthorityError(ValueError):
    pass


TABLES = {"services": "service", "d1_databases": "d1", "r2_buckets": "r2_bucket",
          "secrets_store_secrets": "secrets_store_secret"}
SINGLE = {"assets": "assets", "browser": "browser", "version_metadata": "version_metadata"}


def inventory(repo):
    entries = []
    for table, kind in TABLES.items():
        for item in repo.get(table, []):
            entry = {"name": item["binding"], "type": kind}
            if kind == "service":
                entry.update(service=item["service"], environment=item.get("environment", "production"))
            elif kind == "d1":
                value = item["database_id"]
                if str(UUID(value)) != value or not UUID(value).int:
                    raise BindingAuthorityError("repository D1 id must be a canonical nonzero UUID")
                entry["id"] = value
            elif kind == "r2_bucket":
                entry.update(bucket_name=item["bucket_name"], jurisdiction=item.get("jurisdiction"))
            else:
                entry.update(store_id=item["store_id"], secret_name=item["secret_name"])
            entries.append(entry)
    for table, kind in SINGLE.items():
        if table in repo:
            entries.append({"name": repo[table]["binding"], "type": kind})
    entries.extend({"name": name, "type": "secret_text"}
                   for name in repo.get("secrets", {}).get("required", []))
    return index(entries)


def identity(entry):
    kind = entry["type"]
    result = {"name": entry["name"], "type": kind}
    if kind == "service":
        result.update(service=entry.get("service"), environment=entry.get("environment") or "production")
    elif kind == "d1":
        result["id"] = entry.get("id", entry.get("database_id"))
    elif kind == "r2_bucket":
        result.update(bucket_name=entry.get("bucket_name"), jurisdiction=entry.get("jurisdiction"))
    elif kind == "secrets_store_secret":
        result.update(store_id=entry.get("store_id"), secret_name=entry.get("secret_name"))
    return result


def index(entries):
    result = {}
    for entry in entries:
        name = entry.get("name")
        if not isinstance(name, str) or not name.isascii() or not name.isidentifier():
            raise BindingAuthorityError("invalid binding name")
        if name in result:
            raise BindingAuthorityError("duplicate binding name: " + name)
        result[name] = identity(entry)
    return result


def binding_diff(before, after):
    """Compare targets internally; never return targets or variable values."""
    return {
        "added": [{"name": n, "type": after[n]["type"]} for n in sorted(after.keys() - before.keys())],
        "removed": [{"name": n, "type": before[n]["type"]} for n in sorted(before.keys() - after.keys())],
        "changed": [{"name": n, "type": after[n]["type"], "previous_type": before[n]["type"]}
                    for n in sorted(before.keys() & after.keys()) if before[n] != after[n]],
    }


def enforce_removal(diff, allowed=False):
    # A type replacement also removes the previous binding identity.
    if (diff["removed"] or any(x["type"] != x["previous_type"] for x in diff["changed"])) and not allowed:
        raise BindingAuthorityError("binding removal requires allow_binding_removal=true")


def emit_diff(diff):
    for operation, entries in diff.items():
        for entry in entries:
            print("B62_BINDING_DIFF=" + json.dumps({"operation": operation, **entry}, sort_keys=True))
    print("B62_BINDING_DIFF_COUNTS=" + json.dumps({k: len(v) for k, v in diff.items()}, sort_keys=True))


def verify_expected(expected, actual):
    diff = binding_diff(expected, actual)
    if any(diff.values()):
        emit_diff(diff)
        raise BindingAuthorityError("served bindings differ from repository plan")
