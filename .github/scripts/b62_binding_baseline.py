#!/usr/bin/env python3
"""#5223: the approved Worker binding baseline, compared by name and type.

Why this exists
---------------
The Owner D1 release preparation used to pin the live binding set of each
Worker with a magic count.  That count was written once and never revised, so
every later *reviewed* additive install (a Grafana OTLP secret, an Oracle Mesh
secrets-store reference, a B14 caller-proof secret, a separate B62 web-xlsx
database, ...) silently blocked the release path with an opaque
``BINDING_COUNT_UNEXPECTED``.

A count cannot say which binding changed.  A reviewed name+type set can: a
missing binding and an unexpected binding are two different, actionable
drifts.  The baseline therefore replaces the count, and the comparison is by
name and type.

The baseline is a review artifact
---------------------------------
``.github/binding_baselines/<worker>.json`` is the reviewed statement of the
binding set each Worker is allowed to serve.  It carries **names and types
only** — no values, no database ids, no secret content.  A Worker that needs
a new binding gets it in a reviewed change that updates the baseline in the
same commit, so the expectation cannot rot unnoticed.

Diagnostics stay bounded
------------------------
Public diagnostics are bounded codes and counts, never payload contents, in
line with the rest of the release path.  The committed baseline is where the
binding names are reviewed; the log only reports how far the live set drifted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASELINE_DIR = Path(__file__).resolve().parents[1] / "binding_baselines"

# The Workers this baseline covers.  The key is the Worker script name.
SUPPORTED_WORKERS = ("ai-revenue-korean-ai-platform", "padiem-ai-engine", "padiem-chat")


class BindingBaselineError(RuntimeError):
    """Bounded public diagnostics for a baseline problem."""


def baseline_path(worker: str) -> Path:
    if worker not in SUPPORTED_WORKERS:
        raise BindingBaselineError("WORKER_UNKNOWN")
    return BASELINE_DIR / f"{worker}.json"


def load_baseline(worker: str) -> dict[str, str]:
    """Return the reviewed ``name -> type`` set for ``worker``."""

    path = baseline_path(worker)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BindingBaselineError("BASELINE_UNREADABLE") from exc
    if not isinstance(payload, dict) or payload.get("worker") != worker:
        raise BindingBaselineError("BASELINE_WORKER_MISMATCH")
    entries = payload.get("bindings")
    if not isinstance(entries, list) or not entries:
        raise BindingBaselineError("BASELINE_EMPTY")
    expected: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise BindingBaselineError("BASELINE_ENTRY_INVALID")
        name = entry.get("name")
        kind = entry.get("type")
        if not isinstance(name, str) or not name or not isinstance(kind, str) or not kind:
            raise BindingBaselineError("BASELINE_ENTRY_INVALID")
        if set(entry) != {"name", "type"}:
            # A baseline entry carries an identity and a kind, nothing else.
            raise BindingBaselineError("BASELINE_ENTRY_INVALID")
        if name in expected:
            raise BindingBaselineError("BASELINE_DUPLICATE_NAME")
        expected[name] = kind
    return expected


def extract_entries(payload: object) -> list[tuple[str, str]]:
    """Return the ``(name, type)`` pairs of a Cloudflare Worker payload.

    Accepts the two shapes the release path reads: ``GET /settings``
    (``result.bindings``) and ``GET /versions/{id}``
    (``result.resources.bindings``), including the keyed-dict form.  Only the
    identity and the kind are read; no value, id or secret is touched.
    """

    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise BindingBaselineError("PAYLOAD_ENVELOPE_INVALID")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise BindingBaselineError("PAYLOAD_RESULT_INVALID")
    if "bindings" in result:
        bindings = result["bindings"]
    else:
        resources = result.get("resources")
        if not isinstance(resources, dict):
            raise BindingBaselineError("PAYLOAD_RESULT_INVALID")
        bindings = resources.get("bindings")
    if isinstance(bindings, dict):
        entries = []
        for key, value in bindings.items():
            if not isinstance(key, str) or not key or not isinstance(value, dict):
                raise BindingBaselineError("PAYLOAD_BINDING_INVALID")
            if "name" in value and value["name"] != key:
                raise BindingBaselineError("PAYLOAD_BINDING_INVALID")
            entries.append({**value, "name": key})
        bindings = entries
    if not isinstance(bindings, list):
        raise BindingBaselineError("PAYLOAD_BINDING_INVALID")
    out: list[tuple[str, str]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            raise BindingBaselineError("PAYLOAD_BINDING_INVALID")
        name = binding.get("name")
        kind = binding.get("type")
        if not isinstance(name, str) or not name or not isinstance(kind, str) or not kind:
            raise BindingBaselineError("PAYLOAD_BINDING_INVALID")
        out.append((name, kind))
    return out


def compare_entries(
    live: list[tuple[str, str]], expected: dict[str, str]
) -> tuple[list[str], list[str]]:
    """Compare the live set against the baseline.

    Returns ``(missing, unexpected)`` as binding **names**.  A name in
    ``missing`` is approved but not served; a name in ``unexpected`` is served
    but not approved.  A name served with a different type counts as both.
    """

    live_map: dict[str, str] = {}
    for name, kind in live:
        if name in live_map:
            raise BindingBaselineError("PAYLOAD_DUPLICATE_NAME")
        live_map[name] = kind
    missing = sorted(
        name for name, kind in expected.items()
        if name not in live_map or live_map[name] != kind
    )
    unexpected = sorted(name for name in live_map if name not in expected)
    return missing, unexpected


def assert_matches_baseline(worker: str, payload: object) -> int:
    """Fail closed unless the live payload matches the reviewed baseline.

    Returns the live binding count.  Raises :class:`BindingBaselineError` with
    a bounded code on any drift.
    """

    expected = load_baseline(worker)
    live = extract_entries(payload)
    missing, unexpected = compare_entries(live, expected)
    if missing or unexpected:
        raise BindingBaselineError("BINDING_SET_DRIFT")
    return len(live)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", required=True, choices=list(SUPPORTED_WORKERS))
    parser.add_argument(
        "--payload", required=True, type=Path,
        help="A Cloudflare Worker settings or version payload (JSON).",
    )
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.payload.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("BINDING_BASELINE=BLOCKED;REASON=PAYLOAD_UNREADABLE", file=sys.stderr)
        return 2
    try:
        count = assert_matches_baseline(args.worker, payload)
    except BindingBaselineError as exc:
        # Bounded code and counts only: never the binding names, never a value.
        missing, unexpected = 0, 0
        try:
            expected = load_baseline(args.worker)
            live = extract_entries(payload)
            missing, unexpected = (
                len(compare_entries(live, expected)[0]),
                len(compare_entries(live, expected)[1]),
            )
        except BindingBaselineError:
            pass
        print(
            f"BINDING_BASELINE=BLOCKED;REASON={exc};WORKER={args.worker};"
            f"MISSING={missing};UNEXPECTED={unexpected}",
            file=sys.stderr,
        )
        return 2
    print(f"BINDING_BASELINE=PASS;WORKER={args.worker};BINDINGS={count}")
    print("BINDING_BASELINE_VALUES_EMITTED=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
