"""Measure how the pipeline behaves on a large catalog.

This script builds a synthetic catalog of the requested size, runs the same
pipeline over it and prints the measured throughput, so the capacity figures in
the pilot report come from a run rather than from arithmetic.

    python scripts/scale_check.py --rows 30000

It writes nothing outside the directory it is given, and it never touches a
real catalog.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.pipeline import run_pipeline  # noqa: E402

CATEGORIES = ("베어링", "볼트/너트", "센서", "호스/튜브", "계측기", "윤활유", "알루미늄", "벨트")
MAKERS = ("한빛", "유니크", "스틸", "센서텍", "오일텍", "알루미늄텍", "벨트코어", "메ASURE")
SUPPLIERS = ("대한물산", "한일무역", "한국산업", "동양패스", "서남전자", "석화케미칼")


def build_catalog(path: Path, rows: int) -> None:
    """Write a synthetic catalog with a realistic duplicate and defect rate."""

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\r\n")
        writer.writerow(
            [
                "품목코드",
                "상품명",
                "모델명",
                "제조사",
                "공급사",
                "규격",
                "단위",
                "분류",
                "매입가",
                "판매가",
                "메모",
            ]
        )
        for index in range(rows):
            group = index // 2 if index % 17 == 0 else index
            code = f"IT-{group:06d}" if index % 23 else ""
            unit = "EA" if index % 3 else "본"
            writer.writerow(
                [
                    code,
                    f"품목 명칭 {group}",
                    f"MDL-{group:06d}",
                    MAKERS[index % len(MAKERS)] + "코리아",
                    SUPPLIERS[index % len(SUPPLIERS)],
                    f"규격 {group // 4}",
                    unit,
                    CATEGORIES[index % len(CATEGORIES)],
                    "" if index % 19 == 0 else str(1000 + index),
                    "" if index % 31 == 0 else str(1500 + index),
                    "",
                ]
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=30_000)
    parser.add_argument("--keep", default=None, help="Directory to keep the generated files in.")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        catalog = work / "scale_catalog.csv"
        output = work / "out"

        started = time.perf_counter()
        build_catalog(catalog, args.rows)
        build_ms = (time.perf_counter() - started) * 1000

        report = run_pipeline(source=catalog, output_dir=output)

        summary = {
            "rows": args.rows,
            "catalog_build_ms": round(build_ms, 1),
            "row_count": report.row_count,
            "auto_ok_count": report.auto_ok_count,
            "review_required_count": report.review_required_count,
            "duplicate_group_count": report.duplicate_group_count,
            "duplicate_skipped_blocks": report.duplicate_skipped_blocks,
            "duplicate_compared_pairs": report.duplicate_compared_pairs,
            "timings_ms": {key: round(value, 1) for key, value in report.timings_ms.items()},
            "rows_per_second_total": round(
                report.row_count / max(report.timings_ms.get("total", 1.0) / 1000, 0.001)
            ),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        if args.keep:
            keep = Path(args.keep)
            keep.mkdir(parents=True, exist_ok=True)
            for item in output.iterdir():
                (keep / item.name).write_bytes(item.read_bytes())
            (keep / catalog.name).write_bytes(catalog.read_bytes())
            print(f"kept outputs in {keep}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
