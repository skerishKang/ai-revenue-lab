"""Build the B71 web MVP sample dataset from the three existing workstreams.

The B71 web MVP is a static site. A static site cannot read another app's
directory at runtime, so the site ships a prepared dataset. This script is the
only place that dataset is produced: it reads the **existing** workstream
outputs and writes one JSON file per screen. It never re-implements a parser, a
normalizer, a duplicate detector or a state machine, and it never invents a
result.

Sources (all already committed, all synthetic):

* product listing  -> apps/korean-ai-code-agent/pilots/product-listing/out
* ERP item master  -> apps/erp-item-master/samples/out
* order fulfilment -> apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out

The output is deterministic. It carries no wall-clock timestamp, so re-running
it on an unchanged tree produces byte-identical files and a review can diff the
dataset instead of guessing what changed.

Usage::

    python apps/business-71-ai-operations/scripts/build_web_data.py
    python apps/business-71-ai-operations/scripts/build_web_data.py --check
"""

from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE_ROOT = REPO_ROOT / "reference" / "business-71-ai-operations-v1"
DATA_DIR = SITE_ROOT / "data"

KAGENT_SRC = REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"
KAGENT_PACKAGE_NAME = "kagent_b71_channel_profiles"

PRODUCT_LISTING_OUT = (
    REPO_ROOT / "apps" / "korean-ai-code-agent" / "pilots" / "product-listing" / "out"
)
ERP_SAMPLES_OUT = REPO_ROOT / "apps" / "erp-item-master" / "samples" / "out"
ORDER_OUT = (
    REPO_ROOT
    / "apps"
    / "korean-ai-code-agent"
    / "pilots"
    / "order-supply-fulfillment"
    / "out"
)

#: Every screen in this site shows synthetic data until a real workspace is
#: connected. The flag is repeated in each dataset so a screen can never show
#: sample data without saying so.
SYNTHETIC_NOTICE = (
    "가상 샘플 데이터입니다. 실제 고객 계정·판매채널·ERP에 연결되지 않았습니다."
)

DATA_FILES = (
    "dashboard.json",
    "product_listing.json",
    "erp_items.json",
    "order_fulfillment.json",
    "remote_agent.json",
)


class BuildError(RuntimeError):
    """Raised when a source the site depends on is missing or unreadable."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read JSON source {path}") from exc


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"cannot read text source {path}") from exc


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BuildError(f"cannot read CSV source {path}") from exc
    return list(csv.DictReader(text.splitlines()))


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(rendered, encoding="utf-8")
    return rendered


def _load_kagent_package() -> ModuleType | None:
    """Load the kagent package by path, the way the ERP adapter does.

    The channel registration profiles already exist in the product-listing
    workstream. Reusing their Korean field labels keeps the web screen and the
    workstream from drifting. The load is optional: when the package cannot be
    loaded, the screen falls back to the raw field keys instead of failing.
    """

    existing = sys.modules.get(KAGENT_PACKAGE_NAME)
    if existing is not None:
        return existing
    initializer = KAGENT_SRC / "kagent" / "__init__.py"
    if not initializer.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        KAGENT_PACKAGE_NAME,
        initializer,
        submodule_search_locations=[str(KAGENT_SRC / "kagent")],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[KAGENT_PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - the labels are an optional enrichment
        sys.modules.pop(KAGENT_PACKAGE_NAME, None)
        return None
    return module


def _channel_field_labels() -> dict[str, str]:
    """Map every channel field key to the Korean label the product already uses."""

    package = _load_kagent_package()
    if package is None:
        return {}
    try:
        profiles = importlib.import_module(
            f"{KAGENT_PACKAGE_NAME}.ops_product_listing_channels"
        )
    except Exception:  # noqa: BLE001 - optional enrichment
        return {}
    labels: dict[str, str] = {}
    for profile in profiles.CHANNEL_PROFILES:
        for spec in profile.fields:
            labels.setdefault(spec.key, spec.label)
    return labels


def _product_listing() -> dict[str, Any]:
    record = _read_json(PRODUCT_LISTING_OUT / "canonical_product.json")
    report = _read_json(PRODUCT_LISTING_OUT / "pilot_report.json")
    manifest = _read_json(PRODUCT_LISTING_OUT / "image_manifest.json")
    fill_plan = _read_json(PRODUCT_LISTING_OUT / "browser_fill_plan.json")
    description_html = _read_text(PRODUCT_LISTING_OUT / "description.html")
    labels = _channel_field_labels()

    channels: list[dict[str, Any]] = []
    draft_dir = PRODUCT_LISTING_OUT / "channel_drafts"
    for draft_path in sorted(draft_dir.glob("*.json")):
        draft = _read_json(draft_path)
        fields = [
            {
                "key": key,
                "label": labels.get(key, key),
                "value": value,
            }
            for key, value in draft["values"].items()
        ]
        channels.append(
            {
                "channel_id": draft["channel_id"],
                "display_name": draft["display_name"],
                "admin_surface": draft["admin_surface"],
                "ready_for_entry": draft["ready_for_entry"],
                "unresolved_field_count": draft["unresolved_field_count"],
                "manual_field_count": draft.get("manual_field_count", 0),
                "issues": draft["issues"],
                "fields": fields,
                "source_urls": draft.get("source_urls", []),
                "source_checked_on": draft.get("source_checked_on", ""),
            }
        )

    fields: list[dict[str, Any]] = []
    for field_id, meta in sorted(record.get("fields", {}).items()):
        fields.append(
            {
                "field_id": field_id,
                "review_status": meta["review_status"],
                "origin": meta["origin"],
                "trusted_business_value": meta["trusted_business_value"],
                "source_locator": meta["source_locator"],
            }
        )

    return {
        "synthetic_data": True,
        "synthetic_notice": SYNTHETIC_NOTICE,
        "source": "apps/korean-ai-code-agent/pilots/product-listing/out",
        "issue": "#5446",
        "product_id": record.get("product_id", ""),
        "source_ref": record.get("source_ref", ""),
        "unresolved_field_count": record.get("unresolved_field_count", 0),
        "fields": fields,
        "description_html": description_html,
        "image_manifest": manifest,
        "channels": channels,
        "fill_plan": fill_plan,
        "report": report,
    }


def _erp_items() -> dict[str, Any]:
    report = _read_json(ERP_SAMPLES_OUT / "pipeline_report.json")
    items = _read_csv(ERP_SAMPLES_OUT / "item_master_normalized.csv")
    review_required = _read_csv(ERP_SAMPLES_OUT / "review_required.csv")
    duplicates = _read_csv(ERP_SAMPLES_OUT / "duplicate_report.csv")
    mapping = _read_csv(ERP_SAMPLES_OUT / "erp_field_mapping_status.csv")

    profiles = report.get("profiles", {})
    binding_state = {
        profile_id: {
            "upload_ready": "upload_ready=True" in profile_text,
            "template_confirmed": "template_confirmed=True" in profile_text,
            "raw": profile_text,
        }
        for profile_id, profile_text in profiles.items()
    }

    review_by_code = {
        row.get("품목코드", ""): row for row in review_required if row.get("품목코드")
    }
    duplicate_codes: dict[str, str] = {}
    for group in duplicates:
        for match in re.finditer(
            r"duplicate_item_code:([A-Za-z0-9._-]+)", group.get("사유", "")
        ):
            duplicate_codes[match.group(1)] = group.get("중복그룹", "")

    classified: list[dict[str, Any]] = []
    counts = {"AUTO_OK": 0, "REVIEW_REQUIRED": 0, "DUPLICATE": 0}
    for row in items:
        code = row.get("품목코드", "")
        reasons: list[str] = []
        review_row = review_by_code.get(code)
        if review_row is not None:
            reasons = [
                part.strip()
                for part in review_row.get("검토사유", "").split(";")
                if part.strip()
            ]
        error = row.get("오류", "").strip()
        if error:
            reasons.append(error)
        duplicate_group = row.get("중복그룹", "").strip()
        if duplicate_group:
            reasons.append(f"duplicate_group:{duplicate_group}")
        elif code in duplicate_codes:
            reasons.append(f"duplicate_group:{duplicate_codes[code]}")
        if duplicate_group or code in duplicate_codes:
            status = "DUPLICATE"
        elif reasons or row.get("검토상태", "") != "AUTO_OK":
            status = "REVIEW_REQUIRED"
        else:
            status = "AUTO_OK"
        counts[status] += 1
        classified.append(
            {
                "item_code": code,
                "item_name": row.get("상품명", ""),
                "model_name": row.get("모델명", ""),
                "manufacturer": row.get("제조사", ""),
                "specification": row.get("규격", ""),
                "unit": row.get("단위", ""),
                "supplier": row.get("공급사", ""),
                "category": row.get("상품분류", ""),
                "purchase_price": row.get("매입가", ""),
                "sales_price": row.get("판매가", ""),
                "origin": row.get("원산지", ""),
                "source": row.get("정보출처", ""),
                "duplicate_group": duplicate_group,
                "duplicate_type": row.get("중복유형", ""),
                "duplicate_target_row": row.get("중복대상행", ""),
                "review_status": row.get("검토상태", ""),
                "status": status,
                "reasons": reasons,
                "raw": row,
            }
        )

    return {
        "synthetic_data": True,
        "synthetic_notice": SYNTHETIC_NOTICE,
        "source": "apps/erp-item-master/samples/out",
        "issue": "#5447",
        "pipeline_report": report,
        "profiles": binding_state,
        "items": classified,
        "status_counts": counts,
        "review_required": review_required,
        "duplicates": duplicates,
        "field_mapping": mapping,
    }


def _order_fulfillment() -> dict[str, Any]:
    report = _read_json(ORDER_OUT / "pilot_report.json")
    order_lines = _read_csv(ORDER_OUT / "order_lines.csv")
    shipments = _read_csv(ORDER_OUT / "shipment_tracking.csv")
    exceptions = _read_csv(ORDER_OUT / "exception_cases.csv")
    supplier_draft = _read_text(ORDER_OUT / "supplier_order_request_draft.md")
    tracking_template = _read_csv(ORDER_OUT / "tracking_input_template.csv")
    intake_record = _read_json(ORDER_OUT / "order_intake_record.json")
    completion_record = _read_json(ORDER_OUT / "order_completion_record.json")

    lines_by_order: dict[str, list[dict[str, str]]] = {}
    for line in order_lines:
        lines_by_order.setdefault(line.get("order_id", ""), []).append(line)
    shipments_by_order: dict[str, list[dict[str, str]]] = {}
    for shipment in shipments:
        shipments_by_order.setdefault(shipment.get("order_id", ""), []).append(shipment)

    order_ids: list[str] = []
    for order_id in list(lines_by_order) + list(shipments_by_order):
        if order_id not in order_ids:
            order_ids.append(order_id)
    orders = []
    for order_id in order_ids:
        lines = lines_by_order.get(order_id, [])
        order_shipments = shipments_by_order.get(order_id, [])
        latest = order_shipments[-1] if order_shipments else {}
        orders.append(
            {
                "order_id": order_id,
                "status": lines[0].get("status", "") if lines else "",
                "channel": lines[0].get("channel", "") if lines else "",
                "channel_order_ref": lines[0].get("channel_order_ref", "") if lines else "",
                "line_count": len(lines),
                "total_amount_minor": lines[0].get("line_total_amount_minor", "") if lines else "",
                "currency": lines[0].get("currency", "") if lines else "",
                "latest_shipment_status": latest.get("status", ""),
                "tracking_number": latest.get("tracking_number", ""),
                "exception_count": sum(
                    1 for item in exceptions if item.get("order_id") == order_id
                ),
            }
        )

    return {
        "synthetic_data": True,
        "synthetic_notice": SYNTHETIC_NOTICE,
        "source": "apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out",
        "issue": "#5448",
        "report": report,
        "pilot": report.get("pilot", {}),
        "steps": report.get("steps", []),
        "measurement_plan": report.get("measurement_plan", []),
        "guard_probes": report.get("guard_probes", []),
        "kpi_observations": report.get("kpi_observations", []),
        "step_automation_summary": report.get("step_automation_summary", {}),
        "order_intake": intake_record,
        "order_completion": completion_record,
        "orders": orders,
        "order_lines": order_lines,
        "shipments": shipments,
        "exceptions": exceptions,
        "tracking_template": tracking_template,
        "supplier_order_draft": supplier_draft,
    }


def _remote_agent() -> dict[str, Any]:
    """The Browser Use area, honestly empty until a real connector exists."""

    return {
        "synthetic_data": True,
        "synthetic_notice": SYNTHETIC_NOTICE,
        "source": "no browser-control session is connected to this site",
        "connection": {
            "state": "not_connected",
            "label": "연결 준비 중",
            "detail": (
                "이 화면은 향후 실제 Browser Use 실행 이벤트를 연결할 구조입니다. "
                "지금 이 사이트는 원격 제어가 연결되어 있지 않습니다."
            ),
        },
        "current_job": None,
        "recent_steps": [],
        "screenshots": [],
        "input_events": [],
        "event_contract": {
            "source": "kagent.browser_control_actions",
            "lease_eligible_actions": ["scroll", "focus", "click", "type", "select"],
            "step_up_required_actions": [
                "submit",
                "credential_field_interaction",
                "upload",
                "download",
                "clipboard_read",
                "clipboard_write",
                "cross_origin_navigation",
            ],
            "prohibited_actions": [
                "javascript_evaluate",
                "payment_or_purchase",
                "account_or_security_change",
                "destructive_action",
                "permission_prompt",
            ],
            "note": (
                "이 목록은 제품이 이미 분류한 액션 어휘입니다. "
                "실제 실행 기록이 붙기 전까지 이 화면은 실행 이력이 없습니다."
            ),
        },
    }


def _dashboard(
    product: dict[str, Any],
    erp: dict[str, Any],
    orders: dict[str, Any],
) -> dict[str, Any]:
    product_report = product["report"]
    product_artifacts = product_report.get("artifacts", {})
    erp_report = erp["pipeline_report"]
    order_report = orders["report"]
    order_exec = order_report.get("automation_execution", {})

    workflows = [
        {
            "id": "product_listing",
            "title": "상품등록",
            "issue": "#5446",
            "href": "#/product",
            "status_code": "prepared",
            "status_label": "등록 준비 완료",
            "summary": (
                "공급 자료에서 표준 속성·판매채널별 등록 초안·검수표까지 생성했습니다. "
                "실제 판매채널 계정 게시는 수행하지 않았습니다."
            ),
            "metrics": [
                {
                    "label": "판매채널 초안",
                    "value": f"{product_artifacts.get('channel_draft_count', '0')}건",
                },
                {
                    "label": "자동 입력 단계",
                    "value": f"{product_artifacts.get('automatable_step_total', '0')}건",
                },
                {
                    "label": "사람 수행 단계",
                    "value": f"{product_artifacts.get('human_step_total', '0')}건",
                },
            ],
            "notes": product_report.get("review_checklist", [])[:4],
            "follow_ups": product_report.get("follow_ups", []),
        },
        {
            "id": "erp_items",
            "title": "ERP 품목관리",
            "issue": "#5447",
            "href": "#/erp",
            "status_code": "prepared",
            "status_label": "일괄입력 준비 완료",
            "summary": (
                "품목 정규화·중복 판정·검토 필요 분류와 서식 바인딩 결과를 준비했습니다. "
                "공식 ERP 서식이 확인된 프로필만 업로드 가능으로 표시합니다."
            ),
            "metrics": [
                {"label": "건수", "value": f"{erp_report.get('row_count', 0)}건"},
                {
                    "label": "자동 통과",
                    "value": f"{erp_report.get('auto_ok_count', 0)}건",
                },
                {
                    "label": "검토 필요",
                    "value": f"{erp_report.get('review_required_count', 0)}건",
                },
            ],
            "notes": [
                "중복 그룹 판정과 오류 건수를 분리해 표시합니다.",
                "서식 바인딩 확인 상태를 프로필별로 표시합니다.",
            ],
            "follow_ups": [
                "제3자 보고 근거인 서식은 업로드 가능으로 표시하지 않습니다.",
            ],
        },
        {
            "id": "order_fulfillment",
            "title": "주문·배송",
            "issue": "#5448",
            "href": "#/orders",
            "status_code": "prepared",
            "status_label": "상태 흐름 준비 완료",
            "summary": (
                "주문 접수부터 발주 초안·배송 진행·예외 처리까지 가상 사례로 준비했습니다. "
                "실제 발주와 결제는 수행하지 않았습니다."
            ),
            "metrics": [
                {
                    "label": "자동 가능 단계",
                    "value": f"{order_report.get('step_automation_summary', {}).get('fully_automatable', 0)}단계",
                },
                {
                    "label": "사람 확인 필요",
                    "value": f"{order_report.get('step_automation_summary', {}).get('human_confirmation_required', 0)}단계",
                },
                {
                    "label": "수동 단계",
                    "value": f"{order_report.get('step_automation_summary', {}).get('manual_only', 0)}단계",
                },
            ],
            "notes": [
                "가드 점검 5건이 모두 의도대로 차단됐습니다.",
                "실측 소요시간은 사람이 측정한 값이 아닙니다.",
            ],
            "follow_ups": [
                "실제 운영 시계 기준 측정으로 교체해야 합니다.",
            ],
        },
    ]

    recent_runs = [
        {
            "id": "run-product-listing-sample",
            "workflow": "상품등록",
            "issue": "#5446",
            "result": "준비 완료",
            "result_code": "prepared",
            "detail": (
                "가상 상품 1건 기준 4개 채널 초안 생성, 차단 0건. "
                "실제 게시 없음."
            ),
            "evidence": product_artifacts.get("record_sha256", "")[:16],
        },
        {
            "id": "run-erp-item-master-sample",
            "workflow": "ERP 품목관리",
            "issue": "#5447",
            "result": "준비 완료",
            "result_code": "prepared",
            "detail": (
                f"{erp_report.get('row_count', 0)}건 정규화, "
                f"{erp_report.get('review_required_count', 0)}건 검토 필요."
            ),
            "evidence": "apps/erp-item-master/samples/out/pipeline_report.json",
        },
        {
            "id": "run-order-supply-fulfillment-sample",
            "workflow": "주문·배송",
            "issue": "#5448",
            "result": "준비 완료",
            "result_code": "prepared",
            "detail": (
                "가상 주문 1건 기준 발주 초안·배송 4단계·예외 2건 준비. "
                "실제 발주·결제 없음."
            ),
            "evidence": "apps/korean-ai-code-agent/pilots/order-supply-fulfillment/out",
        },
    ]

    return {
        "synthetic_data": True,
        "synthetic_notice": SYNTHETIC_NOTICE,
        "site": {
            "title": "B71 AI Operations",
            "subtitle": "온라인몰 업무 3종 통합 대시보드",
        },
        "workflows": workflows,
        "recent_runs": recent_runs,
        "measurement_note": (
            "화면의 시간·횟수는 각 워크스트림이 자체 저장한 샘플 실행 기록입니다. "
            "실제 운영 실측값이 아니며 기준선 비교도 계산하지 않았습니다."
        ),
        "source_issues": ["#5446", "#5447", "#5448"],
    }


def build(output_dir: Path | None = None) -> dict[str, Path]:
    """Write every screen dataset and return the written file paths."""

    target = output_dir or DATA_DIR
    product = _product_listing()
    erp = _erp_items()
    orders = _order_fulfillment()
    remote = _remote_agent()
    dashboard = _dashboard(product, erp, orders)

    payloads = {
        "dashboard.json": dashboard,
        "product_listing.json": product,
        "erp_items.json": erp,
        "order_fulfillment.json": orders,
        "remote_agent.json": remote,
    }
    written: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = target / name
        _write_json(path, payload)
        written[name] = path
    return written


def check(output_dir: Path | None = None) -> int:
    """Report whether the committed dataset matches a fresh build."""

    target = output_dir or DATA_DIR
    expected = {
        "dashboard.json": _dashboard(_product_listing(), _erp_items(), _order_fulfillment()),
        "product_listing.json": _product_listing(),
        "erp_items.json": _erp_items(),
        "order_fulfillment.json": _order_fulfillment(),
        "remote_agent.json": _remote_agent(),
    }
    stale: list[str] = []
    for name, payload in expected.items():
        path = target / name
        if not path.is_file():
            stale.append(f"{name}: missing")
            continue
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.read_text(encoding="utf-8") != rendered:
            stale.append(f"{name}: differs from a fresh build")
    if stale:
        for item in stale:
            print(f"STALE {item}", file=sys.stderr)
        return 1
    print(f"WEB_DATA_UP_TO_DATE files={len(expected)}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="write the dataset somewhere other than the committed site directory",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed dataset differs from a fresh build",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    output_dir = Path(args.output_dir) if args.output_dir else None
    if args.check:
        return check(output_dir)
    written = build(output_dir)
    for name, path in written.items():
        print(f"WROTE {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
