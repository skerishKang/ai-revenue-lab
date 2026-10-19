"""#3711: B62↔B66 PDF renderer binding mutation reads use the canonical CLI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-b66-pdf-renderer-service-binding-gate.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_activation_and_rollback_use_canonical_cli_only_for_active_version() -> None:
    text = source()
    activation = text.split("\n  activate-b66-pdf-renderer-binding:", 1)[1].split(
        "\n  rollback-b66-pdf-renderer-binding:", 1
    )[0]
    rollback = text.split("\n  rollback-b66-pdf-renderer-binding:", 1)[1]
    assert activation.count("cloudflare_served_version_cli.py resolve-active") == 2
    assert rollback.count("cloudflare_served_version_cli.py resolve-active") == 2
    for runtime in (activation, rollback):
        assert ".result.deployments[0].versions[0].version_id" not in runtime
        assert ".result.deployments[0].versions[0].percentage" not in runtime
        assert "(.result.deployments[0].versions | length) == 1" not in runtime


def test_pre_reads_fail_closed_and_keep_latest_equals_active() -> None:
    text = source()
    assert text.count('active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active --deployments "${deployments}")"') >= 2
    assert text.count('test "${active}" = "${latest}"') >= 2
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in text


def test_postmutation_and_rollback_polls_keep_existing_budget() -> None:
    text = source()
    activation = text.split("\n  activate-b66-pdf-renderer-binding:", 1)[1].split(
        "\n  rollback-b66-pdf-renderer-binding:", 1
    )[0]
    rollback = text.split("\n  rollback-b66-pdf-renderer-binding:", 1)[1]
    for runtime in (activation, rollback):
        assert "for _ in $(seq 1 30)" in runtime
        assert "sleep 2" in runtime
        assert 'if ! active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active --deployments "${deployments}")"; then' in runtime
        assert 'active=""' in runtime


def test_binding_and_source_invariants_are_preserved() -> None:
    text = source()
    for token in (
        "B62_WORKER: padiem-chat",
        "PDF_WORKER: padiem-b66-pdf-renderer",
        "PDF_BINDING: B66_PDF_RENDERER_SERVICE",
        "SOURCE_ETAG_UNCHANGED=PASS",
        "EXISTING_BINDINGS_UNCHANGED=PASS",
        "PUBLIC_TOPOLOGY_UNCHANGED=PASS",
        "WORKER_SOURCE_REDEPLOY=NO",
        "SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO",
        "ROLLBACK_SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO",
    ):
        assert token in text


def test_mutation_remains_manual_dispatch_only() -> None:
    text = source()
    assert "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_b66_pdf_renderer_binding' }}" in text
    assert "${{ github.event_name == 'workflow_dispatch' && inputs.mode == 'rollback_b66_pdf_renderer_binding' }}" in text


def test_cli_and_regression_test_retrigger_source_contract() -> None:
    text = source()
    paths = text.split("on:", 1)[1].split("workflow_dispatch:", 1)[0]
    assert ".github/scripts/cloudflare_served_version.py" in paths
    assert ".github/scripts/cloudflare_served_version_cli.py" in paths
    assert ".github/tests/test_3711_b62_b66_pdf_served_version_cli_adoption.py" in paths
    assert CLI.is_file()
