#!/usr/bin/env python3
"""Verify the B71 web MVP as a served site, not as a set of files.

The check starts a local static HTTP server over this directory, then proves:

* the entry page and every dataset file are actually served over HTTP;
* the entry page references the local stylesheet and script and no remote
  origin, so the deployed page cannot depend on a third party;
* the served dataset satisfies the screen contract the site renders;
* the site carries the synthetic-data statement on every screen dataset.

It writes ``evidence/validation.json`` so the result is reviewable.

Usage::

    python reference/business-71-ai-operations-v1/evidence/validate-web.py
"""

from __future__ import annotations

import json
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

SITE_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = SITE_ROOT / "evidence" / "validation.json"

DATASETS = (
    "dashboard.json",
    "product_listing.json",
    "erp_items.json",
    "order_fulfillment.json",
    "remote_agent.json",
)

#: Text that would mean a real customer record leaked into the published site.
FORBIDDEN_MARKERS = (
    "@gmail.com",
    "@naver.com",
    "010-",
    "011-",
)

REMOTE_ASSET_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE
)


class ValidationError(RuntimeError):
    """Raised when the served site fails one of its own contracts."""


def _fetch(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=20) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()
    except URLError as exc:
        raise ValidationError(f"the local server did not answer {url}: {exc}") from exc


def validate() -> dict[str, object]:
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    checks: list[dict[str, object]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            raise ValidationError(f"{name}: {detail}")

    try:
        status, index_bytes = _fetch(f"{base}/index.html")
        record("index_served", status == 200, f"HTTP {status}, {len(index_bytes)} bytes")
        index_text = index_bytes.decode("utf-8")

        record(
            "index_references_local_assets",
            "./styles/app.css" in index_text and "./scripts/app.js" in index_text,
            "the entry page references the local stylesheet and script",
        )
        record(
            "index_has_no_remote_asset",
            REMOTE_ASSET_RE.search(index_text) is None,
            "the entry page loads no remote script, style or image",
        )

        datasets: dict[str, object] = {}
        for name in DATASETS:
            status, payload = _fetch(f"{base}/data/{name}")
            record(f"dataset_served:{name}", status == 200, f"HTTP {status}")
            try:
                datasets[name] = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError(f"{name} is not readable JSON") from exc
            record(
                f"dataset_declares_synthetic:{name}",
                datasets[name].get("synthetic_data") is True,
                "the dataset states that it carries synthetic data",
            )

        dashboard = datasets["dashboard.json"]
        record(
            "dashboard_lists_three_workflows",
            len(dashboard.get("workflows", [])) == 3,
            f"{len(dashboard.get('workflows', []))} workflows",
        )
        record(
            "dashboard_lists_three_recent_runs",
            len(dashboard.get("recent_runs", [])) == 3,
            f"{len(dashboard.get('recent_runs', []))} recent runs",
        )

        product = datasets["product_listing.json"]
        record(
            "product_lists_four_channels",
            len(product.get("channels", [])) == 4,
            f"{len(product.get('channels', []))} channels",
        )
        record(
            "product_has_description_html",
            "<" in str(product.get("description_html", "")),
            "the product detail HTML preview is present",
        )

        erp = datasets["erp_items.json"]
        items = erp.get("items", [])
        counts = erp.get("status_counts", {})
        record(
            "erp_status_counts_match_items",
            sum(counts.values()) == len(items) and len(items) > 0,
            f"counts {counts} over {len(items)} items",
        )
        record(
            "erp_has_three_statuses",
            set(counts) == {"AUTO_OK", "DUPLICATE", "REVIEW_REQUIRED"},
            f"statuses {sorted(counts)}",
        )

        orders = datasets["order_fulfillment.json"]
        record(
            "orders_lists_orders",
            len(orders.get("orders", [])) >= 1,
            f"{len(orders.get('orders', []))} orders",
        )
        record(
            "orders_have_shipments",
            len(orders.get("shipments", [])) >= 1,
            f"{len(orders.get('shipments', []))} shipments",
        )

        remote = datasets["remote_agent.json"]
        record(
            "remote_is_not_connected",
            remote.get("connection", {}).get("state") == "not_connected",
            "the remote screen states that no session is connected",
        )
        record(
            "remote_has_no_events",
            not remote.get("input_events") and not remote.get("screenshots"),
            "the remote screen carries no execution event or screenshot",
        )

        for name, payload in datasets.items():
            blob = json.dumps(payload, ensure_ascii=False)
            hits = [marker for marker in FORBIDDEN_MARKERS if marker in blob]
            record(
                f"dataset_has_no_contact_marker:{name}",
                not hits,
                f"markers found: {hits}" if hits else "no customer contact marker",
            )
    finally:
        server.shutdown()
        server.server_close()

    return {
        "site": "reference/business-71-ai-operations-v1",
        "checks": checks,
        "check_count": len(checks),
        "result": "PASS" if all(item["passed"] for item in checks) else "FAIL",
    }


def main() -> int:
    try:
        result = validate()
    except ValidationError as exc:
        print(f"WEB_VALIDATION_FAILED {exc}", file=sys.stderr)
        return 1
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"WEB_VALIDATION_PASS checks={result['check_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
