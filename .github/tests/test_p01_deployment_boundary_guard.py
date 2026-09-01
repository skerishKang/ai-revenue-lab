from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_guard():
    script = Path(__file__).resolve().parents[1] / "scripts" / "p01_deployment_boundary_guard.py"
    spec = importlib.util.spec_from_file_location("p01_deployment_boundary_guard", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p01_deployment_boundary_guard_reports_no_live_repo_deployments() -> None:
    guard = _load_guard()
    result = guard.audit()

    assert result["violations"] == []
    assert result["source_integrity_validation"] == "preserved"
    assert result["repository_owned_production_deployment"] == "not_performed"
    assert result["external_cloudflare_pages_preview"] == "separate_platform_state_not_repo_owned_production"


def test_guard_keeps_dry_run_bundle_checks_allowed() -> None:
    guard = _load_guard()

    assert guard._line_has_deployment_command("uv run pywrangler deploy --dry-run --outdir bundle")
    assert guard._line_is_safe("uv run pywrangler deploy --dry-run --outdir bundle")


def test_guard_blocks_live_deploy_commands_in_non_release_context() -> None:
    guard = _load_guard()

    assert guard._line_has_deployment_command("wrangler pages deploy dist")
    assert not guard._line_is_safe("wrangler pages deploy dist")
    assert guard._line_has_deployment_command("uv run pywrangler deploy")
    assert not guard._line_is_safe("uv run pywrangler deploy")
