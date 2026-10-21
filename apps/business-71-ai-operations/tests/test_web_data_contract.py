"""Contract tests for the B71 web MVP dataset and its static site.

These tests prove what the deployed site actually renders:

* the dataset is produced from the three existing workstream outputs and is
  deterministic, so a reviewer can diff it instead of guessing;
* every screen states that it shows synthetic data;
* the screen contract the JavaScript renders matches the data that is shipped;
* the entry page loads no remote origin;
* nothing in the published dataset looks like a customer contact record.

The site itself is served and checked end to end by
``reference/business-71-ai-operations-v1/evidence/validate-web.py``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKSPACE_ROOT.parents[1]
SITE_ROOT = REPO_ROOT / "reference" / "business-71-ai-operations-v1"
BUILDER_PATH = WORKSPACE_ROOT / "scripts" / "build_web_data.py"

DATASETS = (
    "dashboard.json",
    "product_listing.json",
    "erp_items.json",
    "order_fulfillment.json",
    "remote_agent.json",
)

REMOTE_ASSET_RE = re.compile(
    r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE
)

FORBIDDEN_MARKERS = ("@gmail.com", "@naver.com", "010-", "011-")


def _load_builder():
    spec = importlib.util.spec_from_file_location("b71_build_web_data", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["b71_build_web_data"] = module
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    output = tmp_path_factory.mktemp("b71-web-data")
    written = builder.build(output)
    assert set(written) == set(DATASETS)
    return written


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_builder_writes_only_into_its_output_directory(built, tmp_path):
    outside = tmp_path / "outside"
    builder.build(outside)
    assert sorted(p.name for p in outside.iterdir()) == sorted(DATASETS)


def test_builder_is_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    builder.build(first)
    builder.build(second)
    for name in DATASETS:
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_committed_dataset_matches_a_fresh_build():
    assert builder.check() == 0


def test_every_screen_declares_synthetic_data(built):
    for name in DATASETS:
        payload = _read(built[name])
        assert payload["synthetic_data"] is True, name
        assert payload["synthetic_notice"], name


def test_dashboard_lists_three_workflows_and_three_runs(built):
    payload = _read(built["dashboard.json"])
    assert [item["id"] for item in payload["workflows"]] == [
        "product_listing",
        "erp_items",
        "order_fulfillment",
    ]
    assert len(payload["recent_runs"]) == 3
    assert payload["source_issues"] == ["#5446", "#5447", "#5448"]


def test_product_screen_lists_four_channels_with_labels(built):
    payload = _read(built["product_listing.json"])
    channels = payload["channels"]
    assert [item["channel_id"] for item in channels] == [
        "coupang",
        "elevenst",
        "naver_smart_store",
        "own_mall",
    ]
    for channel in channels:
        assert channel["fields"], channel["channel_id"]
        assert all(item["label"] for item in channel["fields"]), channel["channel_id"]
        assert channel["source_checked_on"], channel["channel_id"]
        assert channel["source_urls"], channel["channel_id"]
    assert "<" in payload["description_html"]


def test_erp_status_partition_matches_the_pipeline_report(built):
    payload = _read(built["erp_items.json"])
    counts = payload["status_counts"]
    items = payload["items"]
    assert sum(counts.values()) == len(items)
    assert set(counts) == {"AUTO_OK", "DUPLICATE", "REVIEW_REQUIRED"}
    report = payload["pipeline_report"]
    assert counts["AUTO_OK"] == report["auto_ok_count"]
    assert counts["REVIEW_REQUIRED"] + counts["DUPLICATE"] == report["review_required_count"]
    for item in items:
        if item["status"] == "AUTO_OK":
            assert item["reasons"] == []


def test_erp_binding_state_never_claims_an_unverified_template(built):
    payload = _read(built["erp_items.json"])
    for profile_id, profile in payload["profiles"].items():
        if not profile["template_confirmed"]:
            assert profile["upload_ready"] is False, profile_id


def test_orders_screen_carries_lines_shipments_and_exceptions(built):
    payload = _read(built["order_fulfillment.json"])
    assert payload["orders"]
    assert payload["order_lines"]
    assert payload["shipments"]
    assert payload["exceptions"]
    assert payload["supplier_order_draft"].strip()
    assert payload["pilot"]["real_customer_data_used"] is False
    assert payload["pilot"]["real_order_placed"] is False


def test_remote_screen_is_not_connected_and_has_no_events(built):
    payload = _read(built["remote_agent.json"])
    assert payload["connection"]["state"] == "not_connected"
    assert payload["current_job"] is None
    assert payload["recent_steps"] == []
    assert payload["screenshots"] == []
    assert payload["input_events"] == []
    contract = payload["event_contract"]
    assert "type" in contract["lease_eligible_actions"]
    assert "upload" in contract["step_up_required_actions"]
    assert "submit" in contract["step_up_required_actions"]
    assert "payment_or_purchase" in contract["prohibited_actions"]


def test_dataset_carries_no_contact_marker(built):
    for name in DATASETS:
        blob = json.dumps(_read(built[name]), ensure_ascii=False)
        for marker in FORBIDDEN_MARKERS:
            assert marker not in blob, f"{name} contains {marker!r}"


def test_entry_page_loads_no_remote_origin():
    index_text = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    assert "./styles/app.css" in index_text
    assert "./scripts/app.js" in index_text
    assert REMOTE_ASSET_RE.search(index_text) is None


def test_site_ships_every_dataset_the_controller_requests():
    index_text = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    controller = (SITE_ROOT / "scripts" / "app.js").read_text(encoding="utf-8")
    assert index_text.startswith("<!doctype html>")
    assert 'lang="ko"' in index_text
    for name in DATASETS:
        assert (SITE_ROOT / "data" / name).is_file(), name
        assert name in controller, name
    for route in ("#/dashboard", "#/product", "#/erp", "#/orders", "#/remote"):
        assert route in index_text, route


def test_remote_work_area_renders_the_state_from_the_dataset(built):
    controller = (SITE_ROOT / "scripts" / "app.js").read_text(encoding="utf-8")
    payload = _read(built["remote_agent.json"])
    assert "data.connection.state" in controller
    assert "data.connection.label" in controller
    assert payload["connection"]["label"] == "연결 준비 중"
