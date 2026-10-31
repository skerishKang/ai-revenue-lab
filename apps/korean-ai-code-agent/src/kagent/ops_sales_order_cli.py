"""#5448: command line entry for the virtual online order -> supply -> shipment pilot.

Kept as its own module so the shared ``kagent.cli`` surface stays untouched:
this pilot is a local business-pilot runner, not a product command.

    python -m kagent.ops_sales_order_cli --out-dir pilots/order-supply-fulfillment/out

The runner is offline. It never opens a sales-channel account, never calls a
channel or carrier API, never issues a purchase order and never sends a
message.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .contracts import ContractError
from .ops_sales_order_pilot import (
    DEFAULT_PILOT_SLUG,
    DEFAULT_WORKSPACE_ID,
    OnlineOrderPilotResult,
    SalesOrderPilotError,
    run_online_order_pilot,
)

_APP_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PILOT_DIR = _APP_ROOT / "pilots" / DEFAULT_PILOT_SLUG


def _default_sample_dir() -> Path:
    return _DEFAULT_PILOT_DIR / "sample"


def _default_out_dir() -> Path:
    return _DEFAULT_PILOT_DIR / "out"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kagent-sales-order-pilot",
        description=(
            "Run one virtual online order through order intake, supplier purchase-order "
            "draft, shipment tracking, completion and exception handling, then write "
            "the work products."
        ),
    )
    parser.add_argument(
        "--sample-dir",
        default=str(_default_sample_dir()),
        help="Directory holding the virtual case inputs.",
    )
    parser.add_argument(
        "--out-dir",
        default=str(_default_out_dir()),
        help="Directory the generated work products are written to.",
    )
    parser.add_argument(
        "--workspace-id",
        default=DEFAULT_WORKSPACE_ID,
        help="Product workspace id used for the virtual case.",
    )
    parser.add_argument(
        "--order-id",
        default="order_demo_1",
        help="Internal order id of the virtual case.",
    )
    parser.add_argument(
        "--channel-order-ref",
        default="CH-2026-0011",
        help="Sales-channel order reference of the virtual case.",
    )
    return parser


def _print_summary(result: OnlineOrderPilotResult) -> None:
    summary = {
        "order_id": result.order_id,
        "channel_order_ref": result.channel_order_ref,
        "order_status": result.order_status,
        "supplier_request_status": result.supplier_request_status,
        "outbox_state": result.outbox_state,
        "guard_probe_fired": f"{result.automation_execution['guard_probe_fired_count']}"
        f"/{result.automation_execution['guard_probe_count']}",
        "artifacts": [artifact.path for artifact in result.artifacts],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_online_order_pilot(
            sample_dir=Path(args.sample_dir),
            out_dir=Path(args.out_dir),
            workspace_id=args.workspace_id,
            order_id=args.order_id,
            channel_order_ref=args.channel_order_ref,
        )
    except (ContractError, SalesOrderPilotError, OSError) as exc:
        print(f"KAGENT_SALES_ORDER_PILOT: {exc}", file=sys.stderr)
        return 2
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
