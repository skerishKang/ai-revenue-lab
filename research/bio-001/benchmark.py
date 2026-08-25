from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from bio001.runner import benchmark_dataset


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    keys = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="BIO-001 local-only NIR vein segmentation benchmark"
    )
    parser.add_argument("--dataset-csv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-column", required=True)
    parser.add_argument("--mask-column", required=True)
    parser.add_argument("--sample-id-column")
    parser.add_argument("--nurse-region-column")
    parser.add_argument("--subgroup-column", action="append", default=[])
    parser.add_argument("--vein-label", type=int, default=2)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = benchmark_dataset(
        args.dataset_csv,
        args.manifest,
        image_column=args.image_column,
        mask_column=args.mask_column,
        sample_id_column=args.sample_id_column,
        nurse_region_column=args.nurse_region_column,
        subgroup_columns=tuple(args.subgroup_column),
        vein_label=args.vein_label,
        max_samples=args.max_samples,
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(args.output_csv, report["per_sample"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
