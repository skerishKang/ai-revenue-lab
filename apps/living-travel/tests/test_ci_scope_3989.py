"""#3989: narrow Living Travel checkout without weakening its full CI gates."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/living-travel-ci.yml"


def test_ci_keeps_both_full_suite_roots_and_postgres_health_smoke():
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert 'name: Living Travel CI' in wf
    assert 'run: python -m pytest tests pages-preview/tests -q --durations=30' in wf
    assert 'Run complete functional and static preview suites' in wf
    assert 'Startup health smoke' in wf
    assert 'response.json() == {"status": "ok"}' in wf
    assert 'image: postgres:16' in wf
    assert 'LT_TEST_PG_URL: postgresql://lt_ci@127.0.0.1:5432/lt_ci' in wf
    assert '  pull_request:' in wf and '  push:' in wf
    assert 'branches:\n      - main' in wf
    for forbidden in ('--ignore', '--deselect', '--last-failed',
                      'continue-on-error', '--maxfail', ' -k '):
        assert forbidden not in wf


def test_ci_sparse_scope_keeps_workflow_and_git_history():
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert 'sparse-checkout-cone-mode: false' in wf
    assert 'apps/living-travel/**' in wf
    assert '.github/workflows/living-travel-ci.yml' in wf
    assert 'persist-credentials: false' in wf
    assert 'fetch-depth: 0' in wf
    assert 'git diff --check' in wf
    assert 'git fetch origin' in wf
    assert 'Check whitespace in changed range' in wf
