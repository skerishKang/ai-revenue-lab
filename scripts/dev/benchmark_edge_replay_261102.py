"""#6604 — what the replay store's durability mode costs per signed request.

`full` commits every consumed request id with synchronous=FULL (one fsync).
`normal` keeps the store in WAL with synchronous=NORMAL. This measures the same
work — 200 distinct signed requests through the real verifier — under both, so
the number a host would gain is local to that host's disk.

    python scripts/dev/benchmark_edge_replay_261102.py
"""
from __future__ import annotations

import hashlib
import hmac
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane"))

from com2_edge_proof import EdgeProofVerifier  # noqa: E402

SECRET = "benchmark-only-secret-" + "x" * 32
PATH = "/api/claw/local-access/devices"
REQUESTS = 200


def headers(index: int, at: int) -> dict[str, str]:
    request_id = f"{index:032x}"
    signed = "\n".join(("v1", "GET", PATH, str(at), request_id, "TLSv1.3")).encode()
    proof = "v1=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-edge-at": str(at), "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": "TLSv1.3", "x-padiem-edge-proof": proof}


def run(mode: str, db: Path) -> list[float]:
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode=mode)
    at = int(time.time())
    samples: list[float] = []
    for index in range(REQUESTS):
        started = time.perf_counter()
        assert verifier.verify(method="GET", path=PATH, headers=headers(index, at), now=at) is True
        samples.append((time.perf_counter() - started) * 1000.0)
    return samples


def summary(label: str, samples: list[float]) -> str:
    ordered = sorted(samples)
    p90 = ordered[int(len(ordered) * 0.9) - 1]
    return (f"{label:<7} n={len(samples)} avg={statistics.fmean(samples):7.3f}ms "
            f"p50={statistics.median(samples):7.3f}ms p90={p90:7.3f}ms "
            f"max={ordered[-1]:7.3f}ms")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        full = run("full", root / "full.sqlite3")
        normal = run("normal", root / "normal.sqlite3")
    print(summary("full", full))
    print(summary("normal", normal))
    print(f"avg improvement: {statistics.fmean(full) / statistics.fmean(normal):.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
