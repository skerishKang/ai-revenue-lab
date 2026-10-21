"""COM2 R2 incremental sync: diff the fresh remote inventory against the currently
PUBLISHED generation's full object set (key + size + ETag + SHA-256), copy only
new/changed objects into a new immutable generation, verify size + ETag(MD5) +
SHA-256, and publish a pointer without overwriting the base or earlier generations.

Baseline rule: the comparison base is ALWAYS the active published generation
(r2-staging/current_generation.json -> generations/<gen>/manifest.json), never a
stale ``r2-staging/incoming/`` capture and never the legacy base store alone.

Never overwrites existing verified files; remote-deleted objects are only
recorded, never removed. Prints counts only - never object keys or file bytes.

#5484: the remote object download goes through the COM2 DPAPI secret store, so
the Cloudflare credential is injected into the child process environment only
and never appears in argv, stdout/stderr or a new plaintext file. Without that
credential the download fails with an authentication error, because the COM2
host's own Wrangler OAuth session is expired and must not be relied on. The
inventory Worker that produces the remote listing uses the same store.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGING = ROOT / "r2-staging"
GENERATIONS = STAGING / "generations"
INCOMING = STAGING / "incoming"
CONFIG = ROOT / "wrangler.inventory.toml"
WRANGLER = r"D:\cli\wrangler.cmd"
# The COM2 DPAPI secret store is the only Cloudflare credential path on that
# host. The D1 export and the inventory Worker already use it.
DPAPI_STORE = os.environ.get("COM2_DPAPI_STORE") or \
    r"D:\PADIEM-Servers\infrastructure\secret-store\store.py"
BUCKETS = {"workspace": "padiem-workspace-files",
           "b66": "padiem-b66-cgi-qa-261011",
           "media": "padiem-media"}
POINTER = STAGING / "current_generation.json"


def wrangler_command(*arguments: str) -> list:
    """Build a Wrangler invocation routed through the DPAPI secret store.

    ``store.py run <exe> <args...>`` decrypts the registered secrets and passes
    them to the child process as environment variables, so the Cloudflare token
    never reaches the argument vector, the captured output or the shell history.
    When the store is not present the command is used unchanged, so an offline
    or non-COM2 host keeps its previous behaviour.
    """
    command = [WRANGLER, *arguments]
    if Path(DPAPI_STORE).is_file():
        return [sys.executable, DPAPI_STORE, "run", *command]
    return command


def load_objects(path: Path) -> dict:
    rows = json.loads(Path(path).read_text(encoding="utf-8-sig"))["objects"]
    return {r["key"]: {"key": r["key"], "size": int(r["size"]),
                       "etag": str(r.get("etag", "")).strip('"')} for r in rows}


def active_generation() -> str:
    return json.loads(POINTER.read_text(encoding="utf-8"))["generation"]


def generation_index(generation: str) -> dict:
    """Full object set of a published generation: key -> file/size/sha256/etag/origin."""
    manifest = json.loads(
        (GENERATIONS / generation / "manifest.json").read_text(encoding="utf-8"))
    idx = {label: {} for label in BUCKETS}
    for row in manifest:
        if not row.get("ok"):
            continue
        idx[row["bucket"]][row["key"]] = {
            "file": row["file"], "size": row["size"], "sha256": row["sha256"],
            "etag": str(row.get("etag", "")).strip('"'),
            "origin": row.get("origin", "base"),
            "source_generation": row.get("source_generation"),
        }
    return idx


def compute_diff(generation: str, base: dict) -> dict:
    report = {}
    for label in BUCKETS:
        remote = load_objects(INCOMING / (label + ".json"))
        old = base[label]
        new = [k for k in remote if k not in old]
        changed = [k for k in remote if k in old and (
            remote[k]["size"] != old[k]["size"] or remote[k]["etag"] != old[k]["etag"])]
        deleted = [k for k in old if k not in remote]
        report[label] = {
            "generation": generation,
            "remote_count": len(remote),
            "remote_bytes": sum(v["size"] for v in remote.values()),
            "new": new, "changed": changed, "deleted": deleted,
            "unchanged": len(remote) - len(new) - len(changed),
        }
    return report


def _verify(path: Path, size: int, etag: str):
    if not path.is_file() or path.stat().st_size != size:
        return None
    digest = hashlib.sha256()
    md5 = hashlib.md5()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
            md5.update(chunk)
    if len(etag) == 32 and "-" not in etag and md5.hexdigest() != etag.lower():
        return None
    return {"sha256": digest.hexdigest()}


def fetch_one(label: str, item: dict, dest_dir: Path):
    name = hashlib.sha256(item["key"].encode("utf-8")).hexdigest() + ".bin"
    target = dest_dir / name
    tmp = dest_dir / (name + ".part")
    ok = _verify(target, item["size"], item["etag"])
    if ok:
        return {"key": item["key"], "file": name, "size": item["size"], **ok, "ok": True}
    for _ in range(3):
        tmp.unlink(missing_ok=True)
        proc = subprocess.run(wrangler_command(
                               "r2", "object", "get",
                               BUCKETS[label] + "/" + item["key"], "--remote",
                               "--file", str(tmp), "--config", str(CONFIG)),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding="utf-8", errors="replace", timeout=300)
        if proc.returncode == 0:
            ok = _verify(tmp, item["size"], item["etag"])
            if ok:
                os.replace(tmp, target)
                return {"key": item["key"], "file": name, "size": item["size"], **ok, "ok": True}
        tmp.unlink(missing_ok=True)
    return {"key": item["key"], "file": name, "ok": False, "error": "download_or_validation_failed"}


def print_diff(report: dict) -> None:
    for label in BUCKETS:
        r = report[label]
        print(f'DIFF {label} BASE_GEN={r["generation"]} REMOTE={r["remote_count"]} '
              f'BYTES={r["remote_bytes"]} NEW={len(r["new"])} CHANGED={len(r["changed"])} '
              f'DELETED_REMOTE={len(r["deleted"])} UNCHANGED={r["unchanged"]}', flush=True)


def sync(*, diff_only: bool = False) -> int:
    generation = active_generation()
    base = generation_index(generation)
    report = compute_diff(generation, base)
    print_diff(report)
    if diff_only:
        return 0

    new_generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    gen_dir = GENERATIONS / new_generation
    (gen_dir / "blobs").mkdir(parents=True, exist_ok=True)
    (gen_dir / "inventory").mkdir(parents=True, exist_ok=True)

    delta = {}   # label -> [fetched record]
    failures = {}  # label -> [failed record]
    for label in BUCKETS:
        todo = report[label]["new"] + report[label]["changed"]
        if not todo:
            continue
        dest = gen_dir / "blobs" / label
        dest.mkdir(parents=True, exist_ok=True)
        items = [load_objects(INCOMING / (label + ".json"))[k] for k in todo]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(fetch_one, label, item, dest): item["key"] for item in items}
            for future in as_completed(futures):
                rec = future.result()
                (delta if rec["ok"] else failures).setdefault(label, []).append(rec)
                print("COPY", label, "OK" if rec["ok"] else "FAIL", rec.get("size"), flush=True)

    if failures:
        print("SYNC_ABORTED_FAILURES", sum(len(v) for v in failures.values()))
        for label, rows in failures.items():
            for row in rows:
                print("FAILED", label, row.get("error"))
        return 1

    # Full generation manifest = unchanged (carried from the base generation) + delta.
    manifest = []
    for label in BUCKETS:
        remote = load_objects(INCOMING / (label + ".json"))
        delta_keys = {rec["key"]: rec for rec in delta.get(label, [])}
        for key, item in remote.items():
            if key in delta_keys:
                rec = delta_keys[key]
                manifest.append({"bucket": label, "key": key, "ok": True, "size": item["size"],
                                 "etag": item["etag"], "sha256": rec["sha256"],
                                 "file": rec["file"], "origin": "delta"})
            else:
                if key not in base[label]:
                    raise RuntimeError(f"unresolved_object:{label}")
                row = base[label][key]
                entry = {"bucket": label, "key": key, "ok": True, "size": row["size"],
                         "etag": item["etag"], "sha256": row["sha256"],
                         "file": row["file"], "origin": row["origin"]}
                # A carried object that was itself a delta lives in the EARLIER
                # generation's blobs dir; record its source without re-copying it.
                if row["origin"] == "delta" or row.get("source_generation"):
                    entry["origin"] = "generation"
                    entry["source_generation"] = row.get("source_generation") or generation
                manifest.append(entry)
    (gen_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for label in BUCKETS:
        src = INCOMING / (label + ".json")
        (gen_dir / "inventory" / (label + ".json")).write_text(
            src.read_text(encoding="utf-8-sig"), encoding="utf-8")

    # Verify the new generation (size + SHA-256 of every object) BEFORE publishing.
    from r2_generation import verify as verify_generation
    verified_gen, counts = verify_generation(STAGING, new_generation)
    total_ok = sum(ok for ok, _ in counts.values())
    print("R2_NEW_GENERATION_VERIFIED", verified_gen, "OBJECTS", total_ok, flush=True)

    metadata = {
        "generation": new_generation,
        "created_utc": new_generation,
        "source": "cloudflare_r2_remote_list",
        "base_generation": generation,
        "production_bound": False,
        "buckets": {label: {"objects": report[label]["remote_count"],
                            "bytes": report[label]["remote_bytes"],
                            "new": len(report[label]["new"]),
                            "changed": len(report[label]["changed"]),
                            "deleted_remote": len(report[label]["deleted"])}
                    for label in BUCKETS},
    }
    (gen_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    POINTER.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    copied = sum(len(v) for v in delta.values())
    print("R2_PUBLISHED_GENERATION", new_generation, "DELTA_OBJECTS", copied, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(sync(diff_only="--diff-only" in sys.argv))
