from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CERTIFICATION = ROOT / ".github" / "scripts" / "b62_product_surface_certification_browser_qa.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b62-browser-visual-qa.yml"


def test_certification_covers_required_all_theme_desktop_mobile_matrix() -> None:
    source = CERTIFICATION.read_text(encoding="utf-8")
    for theme in ("light", "dark", "cinematic", "padiem-home", "padiem-glass"):
        assert f'("{theme}",' in source
    assert '("desktop", {"width": 1440, "height": 1000})' in source
    assert '("mobile", {"width": 390, "height": 844})' in source
    assert 'len(report["views"]) != 10' in source
    assert 'report["product_surface_desktop"] = "PASS"' in source
    assert 'report["product_surface_mobile"] = "PASS"' in source
    assert 'report["all_themes"] = "PASS"' in source


def test_certification_preserves_ui_backend_production_truth_boundary() -> None:
    source = CERTIFICATION.read_text(encoding="utf-8")
    assert '"UI_READY": "CERTIFIED_BY_THIS_REPORT"' in source
    assert '"BACKEND_ACTIVE": "NOT_IMPLIED_BY_UI_CERTIFICATION"' in source
    assert '"PRODUCTION_ACTIVE": "NO_CLAIM"' in source
    assert 'report["production_active_claim"] = "NO_UNLESS_SEPARATELY_PROVEN"' in source
    assert '"fake_live_capability_claims": 0' in source
    assert '"platform_authority_duplication": 0' in source
    assert '"production_mutation": False' in source


def test_capability_matrix_routes_non_b62_authority_to_owners() -> None:
    source = CERTIFICATION.read_text(encoding="utf-8")
    assert '"presentation": "PREVIEW_ONLY"' in source
    assert '"guest_state": "HIDDEN"' in source
    assert '"presentation": "PREVIEW_ONLY_FOR_DEMO_FIXTURES"' in source
    assert '"owner": "B14 / IP-ENGINE"' in source
    assert '"owner": "IP-ENGINE / IP-CORE"' in source
    assert '"owner": "Control Plane"' in source
    assert '"owner": "release operations / owning platform"' in source
    for forbidden in (
        "wrangler deploy",
        "cloudflare api token",
        "provider_api_key",
        "model_api_key",
        "git push --force",
    ):
        assert forbidden not in source.lower()


def test_certification_requires_existing_regression_gates() -> None:
    source = CERTIFICATION.read_text(encoding="utf-8")
    for workflow_name in (
        "B62 Padiem Chat CI",
        "B62 Browser Visual QA",
        "B62 Accessibility Browser QA",
        "B62 Auth History Browser QA",
        "B62 Saved Outputs Browser QA",
        "B62 Projects Browser QA",
        "B62 Project Files Browser QA",
        "B62 Document Browser QA",
        "B62 Image Browser QA",
        "B62 Error Retry Browser QA",
        "B62 Conversation Export Browser QA",
        "B62 Conversation Delete Browser QA",
        "P01 Deployment Boundary Guard",
    ):
        assert f'"{workflow_name}"' in source


def test_browser_visual_workflow_runs_and_prints_certification_report() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert ".github/scripts/b62_product_surface_certification_browser_qa.py" in workflow
    assert "Product surface v2 certification browser QA" in workflow
    assert "product-surface-certification-report.json" in workflow
