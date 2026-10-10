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
    # Restrict test selection checks to the pytest command, not the whole
    # workflow: npm --ignore-scripts is required by the original dry-run gate.
    test_step = text.split(
        "      - name: Cloudflare migration and sequence prefix contracts", 1
    )[1].split("      - name: Python syntax gate", 1)[0]
    for forbidden in (
        "--ignore", "--deselect", "--last-failed", "--maxfail",
        "continue-on-error", "|| true", " -k ", " --lf",
    ):
        assert forbidden not in test_step

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
    assert "docker_pid=$!" in text and "npm_pid=$!" in text
    assert 'if wait "$docker_pid"' in text
    assert 'if wait "$npm_pid"' in text
    assert 'test "$docker_result" -eq 0' in text
    assert 'test "$npm_result" -eq 0' in text
    assert "B03_DOCKER_BUILD_EXIT=" in text
    assert "B03_NPM_TOOLING_EXIT=" in text
    # Required: concurrent npm install cannot modify the shipped Docker image.
    ignore = (APP / ".dockerignore").read_text(encoding="utf-8")
    assert "node_modules" in ignore.splitlines()
    assert (APP / "Dockerfile.cloudflare").is_file()
    assert (APP / "wrangler.cloudflare-container.toml").is_file()
    assert (APP / "deploy/cloudflare/worker.py").is_file()
