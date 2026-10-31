"""#5446: command-line runner for the online product listing pilot.

The runner lives in its own module on purpose. Running
``python -m kagent.ops_product_listing`` would import the engine twice (once as
``__main__`` and once as ``kagent.ops_product_listing``), which produces two
distinct ``ChannelFieldKind`` enum classes and silently breaks every
``is``/``isinstance`` comparison between the engine and the channel profiles.

Usage::

    PYTHONPATH=src python -m kagent.ops_product_listing_cli \
        --sample pilots/product-listing/sample \
        --out pilots/product-listing/out

The runner only reads local files and writes local artifacts. It never opens a
seller account and never calls a channel API.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractError
from .ops_product_listing import (
    run_product_listing_pilot,
    parse_supplier_csv,
    parse_supplier_xlsx,
)


def _load_sample(sample_dir: Path) -> tuple[Any, str]:
    supplier_csv = sample_dir / "supplier_products.csv"
    if supplier_csv.exists():
        return (
            parse_supplier_csv(supplier_csv.read_text(encoding="utf-8")),
            supplier_csv.name,
        )
    supplier_xlsx = sample_dir / "supplier_products.xlsx"
    if supplier_xlsx.exists():
        return (
            parse_supplier_xlsx(supplier_xlsx.read_bytes(), name=supplier_xlsx.name),
            supplier_xlsx.name,
        )
    raise ContractError(
        "sample folder must contain supplier_products.csv or supplier_products.xlsx"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kagent.ops_product_listing_cli",
        description="#5446 온라인 상품 등록 시연 파이프라인",
    )
    parser.add_argument("--sample", required=True, help="sample 입력 폴더")
    parser.add_argument("--out", required=True, help="결과 출력 폴더")
    parser.add_argument(
        "--review",
        action="append",
        default=None,
        help=(
            "검수 결과 JSON 파일 (attribute: {status, value}). "
            "여러 번 지정하면 순서대로 적용됩니다."
        ),
    )
    parser.add_argument(
        "--baseline-manual-minutes",
        default=None,
        help="수작업 예상 시간(분). 추정치로만 기록됩니다.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    from .ops_product_listing_channels import CHANNEL_PROFILES

    sample_dir = Path(args.sample)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, source_ref = _load_sample(sample_dir)

    research: Mapping[str, Any] = {}
    research_path = sample_dir / "research_notes.json"
    if research_path.exists():
        research = json.loads(research_path.read_text(encoding="utf-8"))

    reviews: list[Mapping[str, Mapping[str, str]]] = []
    for review_path in args.review or []:
        reviews.append(json.loads(Path(review_path).read_text(encoding="utf-8")))

    baseline = None
    if args.baseline_manual_minutes:
        from decimal import Decimal

        baseline = Decimal(args.baseline_manual_minutes)

    result = run_product_listing_pilot(
        supplier_rows=rows,
        research_notes=research,
        profiles=CHANNEL_PROFILES,
        reviews=reviews,
        product_id=sample_dir.name,
        source_ref=source_ref,
        baseline_manual_minutes=baseline,
    )

    _write_json(out_dir / "canonical_product.json", result.record.safe_dict())
    (out_dir / "description.html").write_text(result.description_html, encoding="utf-8")
    _write_json(
        out_dir / "image_manifest.json",
        {
            "entries": [entry.safe_dict() for entry in result.image_manifest],
            "issues": [issue.safe_dict() for issue in result.image_issues],
        },
    )
    drafts_dir = out_dir / "channel_drafts"
    drafts_dir.mkdir(exist_ok=True)
    for draft in result.drafts:
        _write_json(drafts_dir / f"{draft.channel_id}.json", draft.safe_dict())
    _write_json(
        out_dir / "browser_fill_plan.json",
        [plan.safe_dict() for plan in result.fill_plans],
    )
    _write_json(
        out_dir / "pilot_report.json",
        {
            "measurement": result.measurement.safe_dict(),
            "review_checklist": list(result.review_checklist),
            "follow_ups": list(result.follow_ups),
            "artifacts": dict(result.artifacts),
            "drafts": [
                {
                    "channel_id": draft.channel_id,
                    "display_name": draft.display_name,
                    "ready_for_entry": draft.ready_for_entry,
                    "error_count": len(draft.error_issues),
                    "warning_count": len(draft.warning_issues),
                    "unresolved_field_count": draft.unresolved_field_count,
                }
                for draft in result.drafts
            ],
        },
    )
    print(json.dumps(result.measurement.safe_dict(), ensure_ascii=False, indent=2))
    print(f"OUTPUT_DIR={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
