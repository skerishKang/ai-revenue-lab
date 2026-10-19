from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "com2_tunnel.py"


def _load():
    spec = importlib.util.spec_from_file_location("com2_tunnel_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tunnel = _load()


def test_render_maps_public_services_to_loopback_with_catch_all_last():
    content = tunnel.render_ingress(
        ["chat=chat.example.com", "claw=claw.example.com"],
        tunnel_name="com2-primary",
    )
    assert content.startswith(tunnel.GENERATED_MARKER)
    assert "tunnel: com2-primary" in content
    assert "  - hostname: chat.example.com\n    service: http://127.0.0.1:18764" in content
    assert "  - hostname: claw.example.com\n    service: http://127.0.0.1:18764" in content
    assert "disableChunkedEncoding: false" in content
    assert content.rstrip().endswith("- service: http_status:404")
    assert "127.0.0.1:18717" not in content
    assert "127.0.0.1:18731" not in content


def test_internal_services_cannot_be_mapped_publicly():
    try:
        tunnel.parse_mappings(["b14=b14.example.com"])
    except tunnel.TunnelError as error:
        assert str(error) == "internal_service_not_public"
    else:  # pragma: no cover - failure path
        raise AssertionError("expected internal_service_not_public")


def test_mapping_validation_rejects_unknown_duplicate_and_invalid_values():
    cases = {
        "unknown_service": ["b66=b66.example.com"],
        "duplicate_service": ["chat=a.example.com", "chat=b.example.com"],
        "duplicate_hostname": ["chat=a.example.com", "claw=a.example.com"],
        "invalid_mapping": ["chat"],
        "no_mappings": [],
        "invalid_hostname": ["chat=chat.example.com/path"],
    }
    for expected, mappings in cases.items():
        try:
            tunnel.parse_mappings(mappings)
        except tunnel.TunnelError as error:
            assert str(error) == expected, (mappings, str(error))
        else:  # pragma: no cover - failure path
            raise AssertionError(f"expected {expected}")


def test_hostname_validation_rejects_uppercase_ip_single_label_and_wildcard():
    for value in ("Chat.example.com", "127.0.0.1", "localhost", "*.example.com", "chat..example.com"):
        try:
            tunnel.validate_hostname(value)
        except tunnel.TunnelError as error:
            assert str(error) == "invalid_hostname"
        else:  # pragma: no cover - failure path
            raise AssertionError(value)


def test_write_ingress_refuses_to_overwrite_foreign_config(tmp_path):
    output = tmp_path / "config.yml"
    output.write_text("ingress:\n  - service: http://example.com\n", encoding="utf-8")
    try:
        tunnel.write_ingress(output, ["chat=chat.example.com"])
    except tunnel.TunnelError as error:
        assert str(error) == "refusing_to_overwrite_non_generated_config"
    else:  # pragma: no cover - failure path
        raise AssertionError("expected refusal")
    assert "example.com" in output.read_text(encoding="utf-8")

    report = tunnel.write_ingress(output, ["chat=chat.example.com"], force=True)
    assert report["activated"] is False
    assert output.read_text(encoding="utf-8").startswith(tunnel.GENERATED_MARKER)

    # A generated file may be re-rendered without --force.
    tunnel.write_ingress(output, ["chat=chat.example.com", "claw=claw.example.com"])


def test_write_ingress_report_contains_no_tunnel_credentials(tmp_path):
    output = tmp_path / "config.yml"
    report = tunnel.write_ingress(output, ["chat=chat.example.com"])
    assert report["catch_all"] == "http_status:404"
    assert report["routes"] == [
        {"service": "chat", "hostname": "chat.example.com", "origin": "http://127.0.0.1:18764"}
    ]
    serialized = json.dumps(report)
    for forbidden in ("token", "credentials", "secret"):
        assert forbidden not in serialized.lower()


def test_validate_invokes_cloudflared_with_global_config_flag(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(tunnel.render_ingress(["chat=chat.example.com"]), encoding="utf-8")
    calls: list[list[str]] = []

    def runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, "OK", "")

    report = tunnel.validate_ingress(config, cloudflared=str(config), runner=runner)
    assert calls[0][1:4] == ["tunnel", "--config", str(config)]
    assert calls[0][4:] == ["ingress", "validate"]
    assert report["valid"] is True
    assert report["network_used"] is False
    assert report["output_tail"] == ["OK"]


def test_validate_reports_failure_without_raising(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(tunnel.render_ingress(["chat=chat.example.com"]), encoding="utf-8")

    def runner(argv):
        return subprocess.CompletedProcess(list(argv), 1, "", "ingress rule 1: bad hostname")

    report = tunnel.validate_ingress(config, cloudflared=str(config), runner=runner)
    assert report["valid"] is False
    assert report["exit"] == 1
    assert report["output_tail"] == ["ingress rule 1: bad hostname"]


def test_validate_requires_existing_config(tmp_path):
    try:
        tunnel.validate_ingress(tmp_path / "missing.yml", cloudflared=str(tmp_path))
    except tunnel.TunnelError as error:
        assert str(error) == "config_missing"
    else:  # pragma: no cover - failure path
        raise AssertionError("expected config_missing")


def test_missing_cloudflared_is_a_stable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tunnel.shutil, "which", lambda _name: None)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    try:
        tunnel.find_cloudflared(str(tmp_path / "absent.exe"))
    except tunnel.CloudflaredUnavailable as error:
        assert str(error) == "cloudflared_unavailable"
    else:  # pragma: no cover - failure path
        raise AssertionError("expected cloudflared_unavailable")


def test_cli_render_and_validate_round_trip(tmp_path):
    output = tmp_path / "ingress.yml"
    assert tunnel.main(["render", "--map", "chat=chat.example.com", "--output", str(output)]) == 0
    assert output.is_file()

    def runner(argv):
        return subprocess.CompletedProcess(list(argv), 0, "OK", "")

    report = tunnel.validate_ingress(output, cloudflared=str(output), runner=runner)
    assert report["valid"] is True
