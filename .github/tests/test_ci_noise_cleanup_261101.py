"""Offline contracts for rollback PDF binding and advisory B62 preview."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PDF_GATE = ROOT / ".github/workflows/b66-pdf-renderer-production-gate.yml"
PREVIEW = ROOT / ".github/workflows/b62-pr-preview.yml"


def workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def source_contract():
    steps = workflow(PDF_GATE)["jobs"]["source-contract"]["steps"]
    run = next(s["run"] for s in steps if s.get("name") == "Prove renderer source identity and private topology")
    return run.split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]


@pytest.mark.parametrize("change", ["valid", "missing", "wrong_service", "duplicate"])
def test_pdf_source_contract_validates_rollback_binding(tmp_path, monkeypatch, change):
    renderer = tmp_path / "apps/b66-pdf-renderer/wrangler.toml"
    renderer.parent.mkdir(parents=True)
    renderer.write_bytes((ROOT / "apps/b66-pdf-renderer/wrangler.toml").read_bytes())
    chat = tmp_path / "apps/padiem-chat/wrangler.toml"
    chat.parent.mkdir(parents=True)
    text = (ROOT / "apps/padiem-chat/wrangler.toml").read_text(encoding="utf-8")
    binding = 'binding = "B66_PDF_RENDERER_SERVICE"'
    assert text.count(binding) == 1
    if change == "missing":
        text = text.replace(binding, 'binding = "UNRELATED_SERVICE"')
    elif change == "wrong_service":
        text = text.replace('service = "padiem-b66-pdf-renderer"', 'service = "wrong-renderer"')
    elif change == "duplicate":
        text += '\n[[services]]\nbinding = "B66_PDF_RENDERER_SERVICE"\nservice = "padiem-b66-pdf-renderer"\n'
    chat.write_text(text, encoding="utf-8")
    script = source_contract()
    monkeypatch.chdir(tmp_path)
    if change == "valid":
        exec(script, {})
    else:
        with pytest.raises(AssertionError):
            exec(script, {})


def test_preview_is_advisory_but_still_runs_verification_and_browser_smoke():
    data = workflow(PREVIEW)
    job = data["jobs"]["deploy-preview"]
    assert job["continue-on-error"] is True
    assert job["if"] == "github.event.pull_request.head.repo.full_name == github.repository"
    steps = {s.get("name"): s for s in job["steps"]}
    for name in ("Verify exact-head checkout", "Deploy exact-head static visual preview",
                 "Verify exact-head deployment record", "Browser-smoke immutable Glass Preview"):
        assert name in steps
        assert steps[name].get("continue-on-error") is not True
    assert steps["Upload immutable Preview browser evidence"]["if"] == "always()"
    assert data[True]["pull_request"]["paths"] == [
        "apps/padiem-chat/static/**",
        ".github/workflows/b62-pr-preview.yml",
        ".github/scripts/b62_pr_preview_glass_qa.py",
    ]
