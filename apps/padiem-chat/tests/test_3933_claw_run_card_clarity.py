"""Claw run history clarity is presentational, owner-state driven, and scoped."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "claw-focus-layout.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


def test_status_emphasis_only_uses_canonical_known_statuses():
    assert 'const knownRunStates = ["completed", "waiting_approval", "failed", "cancelled"]' in APP
    assert "if (knownRunStates.includes(run.status)) card.dataset.runState = run.status;" in APP
    assert 'badge.textContent = clawRunStatusLabel(run.status);' in APP
    assert "return text === key ? raw : text;" in APP
    assert "card.dataset.runState = \"completed\";" not in APP


def test_explanations_never_claim_unfinished_work_completed():
    assert 'if (["waiting_approval", "failed", "cancelled"].includes(run.status))' in APP
    assert 'nextStep.textContent = clawT(`claw-runs-next-${run.status}`);' in APP
    assert 'nextStep.setAttribute("role", "note");' in APP
    assert 'renderClawApprovalControls(approvalActions, run.run_id' in APP
    assert 'downloadClawArtifact(artifact.document_id, artifact.filename || "")' in APP
    assert 'const previewable = Boolean(window.PadiemClawPdfPreview?.validHistoricalArtifact?.(artifact));' in APP


def test_korean_and_english_explanations_and_fallbacks():
    ko, en = LOCALE.split("en: {", 1)
    for key in ("claw-runs-next-waiting_approval", "claw-runs-next-failed",
                "claw-runs-next-cancelled"):
        assert f'"{key}"' in ko
        assert f'"{key}"' in en
        assert f'"{key}"' in APP
    assert "아직 완료되지 않았습니다" in ko
    assert "does not prove success" in en


def test_glass_claw_only_and_no_fake_result_state():
    for state in ("completed", "waiting_approval", "failed", "cancelled"):
        assert f'[data-run-state="{state}"]' in CSS
    assert ".claw-run-card-nextstep" in CSS
    assert ".claw-run-card-artifact" in CSS
    assert "html[data-theme=\"padiem-glass\"] .app-shell[data-state=\"claw\"]" in CSS
    scoped = CSS.split("#3933 second UI slice:", 1)[1]
    assert '[data-state="chat"]' not in scoped
    assert '[data-state="home"]' not in scoped
    assert "fetch(" not in scoped
