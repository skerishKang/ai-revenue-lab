"""#3989: keep every B03 Cloudflare M0 security/contract gate on sparse checkout."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/b03-living-fiction-cloudflare-m0-ci.yml"
APP = ROOT / "apps/living-fiction"

def test_b03_m0_full_original_migration_and_upgrade_suites_remain_required():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: B03 Living Fiction Cloudflare M0 CI" in text
    assert "  pull_request:" in text
    assert "apps/living-fiction/**" in text
    assert ".github/workflows/b03-living-fiction-cloudflare-m0-ci.yml" in text
    assert "Cloudflare migration and sequence prefix contracts" in text
    for name in (
        "test_cloudflare_migration_contract.py",
        "test_migration_prefix_guard_3110.py",
        "test_3989_b03_m0_ci_scope.py",
    ):
        assert text.count(f"tests/{name}") == 1, name
        assert (APP / "tests" / name).is_file()
    assert text.count("python -m pytest -q") == 1
    for forbidden in (
        "--ignore", "--deselect", "--last-failed", "--maxfail",
        "continue-on-error", "|| true", " -k ", " --lf",
    ):
        assert forbidden not in text

def test_b03_m0_full_build_and_review_security_remain_required():
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "fetch-depth: 0",
        "persist-credentials: false",
        "sparse-checkout-cone-mode: false",
        "apps/living-fiction/**",
        ".github/workflows/b03-living-fiction-cloudflare-m0-ci.yml",
        "python -m compileall -q app deploy/cloudflare/worker.py",
        "docker build --pull -f Dockerfile.cloudflare",
        "npm install --no-save --ignore-scripts wrangler @cloudflare/containers",
        "npx wrangler deploy --dry-run",
        "git merge-base origin/",
        'git diff --check "$BASE"...HEAD',
        "WRANGLER_DEPLOY_MODE=DRY_RUN_ONLY",
        "PRODUCTION_MUTATION=0",
    ):
        assert required in text, required
    assert (APP / "Dockerfile.cloudflare").is_file()
    assert (APP / "wrangler.cloudflare-container.toml").is_file()
    assert (APP / "deploy/cloudflare/worker.py").is_file()
