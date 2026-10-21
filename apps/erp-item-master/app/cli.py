"""Command line entry point for the ERP item-master pipeline.

    python -m app.cli --source samples/source_items_raw.csv --out samples/out

The command writes every output file and prints one summary line. It never
reaches a network, an ERP account or a model provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .erp_profile import all_profiles
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="erp-item-master",
        description="Normalize a supplier catalog into an ERP item import file.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="The source catalog (.csv or .xlsx).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="The directory the output files are written to.",
    )
    parser.add_argument(
        "--extraction",
        default=None,
        help="Optional JSON file of AI-extracted fields, keyed by item code or row number.",
    )
    parser.add_argument(
        "--profiles",
        default="generic,ecount_api_candidate",
        help="Comma separated import profiles to write.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Print the available import profiles and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_profiles:
        for profile_id, profile in all_profiles().items():
            print(
                f"{profile_id}\ttransport={profile.transport}\t"
                f"template_confirmed={profile.template_confirmed}\t"
                f"upload_ready={profile.upload_ready}"
            )
        return 0

    profile_ids = tuple(
        part.strip() for part in str(args.profiles).split(",") if part.strip()
    )

    report = run_pipeline(
        source=args.source,
        output_dir=args.out,
        extraction_file=args.extraction,
        profile_ids=profile_ids,
    )

    summary = report.to_public_dict()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
