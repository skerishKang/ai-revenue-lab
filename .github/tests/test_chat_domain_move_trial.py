"""Offline tests only: every socket, HTTP and process boundary is blocked."""
import importlib.util
import json
import socket
import subprocess
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location("chat_domain_move_trial", ROOT / ".github/scripts/chat_domain_move_trial.py")
trial = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trial)
SHA = "a" * 40
ZONE = "b" * 32
PRIVATE = "synthetic-private-text-must-not-escape"


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("unstubbed external operation")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(subprocess, "run", denied)
    monkeypatch.setattr(trial, "request", denied)
    monkeypatch.setattr(trial.Gate, "cf", denied)


def arguments(mode="switch", execute=False, **changes):
    values = dict(mode=mode, execute=execute, host=trial.HOST, target_sha=SHA,
                  confirmation=f"{mode.upper()}_CHAT_DOMAIN_TRIAL_{trial.HOST}_{SHA}",
                  out="unused.json", observe_seconds=1, interval_seconds=0.1, connect_timeout=1)
    values.update(changes)
    return SimpleNamespace(**values)


def domain(service=trial.WORKERS["A"], **changes):
    result = dict(hostname=trial.HOST, service=service, id="e" * 40, zone_id=ZONE, zone_name="padiem.net",
                  enabled=True, previews_enabled=False)
    result.update(changes)
    return result


def infra():
    return dict(dns_ok=True, dns_answers=["192.0.2.1"], tls_ok=True, certificate_sha256="c" * 64,
                certificate_not_before_utc="2026-10-01T00:00:00+00:00", certificate_not_after_utc="2026-12-30T00:00:00+00:00")


def http(identity="A"):
    return dict(ok=True, status=200, identity=identity)


class FakeSampler:
    def __init__(self, *args):
        self.epoch = 100
        self.started = False
    def start(self):
        self.started = True
    def finish(self, seconds):
        assert self.started
        return {"http": [dict(http("B"), start_seconds=0, end_seconds=0.2)],
                "infrastructure": [dict(infra(), start_seconds=0, end_seconds=0.2)]}


def setup(monkeypatch, mode="switch", execute=False):
    instance = trial.Trial(arguments(mode, execute), {"CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE})
    source, target = ("A", "B") if mode == "switch" else ("B", "A")
    calls = []
    state = {"owner": source}
    def cf(path, **kwargs):
        calls.append((path, kwargs))
        method = kwargs.get("method", "GET")
        if method == "DELETE":
            state["owner"] = None
            return None
        if method == "PUT":
            state["owner"] = next(key for key, value in trial.WORKERS.items()
                                  if value == kwargs["payload"]["service"])
            return {}
        return [] if state["owner"] is None else [domain(trial.WORKERS[state["owner"]])]
    monkeypatch.setattr(instance.api, "cf", cf)
    def fake_mutate(method, path, payload):
        if method == "PUT":
            instance.result["put_attempts"] += 1
        return instance.api.cf(path, method=method, payload=payload)
    monkeypatch.setattr(instance, "mutate_domain", fake_mutate)
    monkeypatch.setattr(instance.api, "account", lambda: None)
    monkeypatch.setattr(instance.api, "exact_main", lambda: None)
    monkeypatch.setattr(trial, "http_sample", lambda host: http(source))
    monkeypatch.setattr(trial, "infrastructure_sample", lambda *args: infra())
    monkeypatch.setattr(trial, "Sampler", FakeSampler)
    monkeypatch.setattr(trial.time, "monotonic", lambda: 100)
    return instance, calls


@pytest.mark.parametrize("mode", ["switch", "rollback"])
def test_default_dry_run_only_reads_and_records_plan(monkeypatch, mode):
    instance, calls = setup(monkeypatch, mode)
    instance.execute()
    assert all(not kwargs for _, kwargs in calls)
    assert instance.result["put_attempts"] == 0
    assert instance.result["outcome"] == "READ_ONLY_READY"
    assert instance.result["planned_change"]["method"] == "DELETE_THEN_PUT"


def test_dry_run_is_default_and_execute_is_mutually_exclusive():
    base = ["switch", "--target-sha", SHA, "--out", "result.json"]
    assert trial.parser().parse_args(base).execute is False
    assert trial.parser().parse_args(base + ["--dry-run"]).execute is False
    with pytest.raises(SystemExit):
        trial.parser().parse_args(base + ["--dry-run", "--execute"])


def test_real_sampler_records_http_before_start_returns(monkeypatch):
    monkeypatch.setattr(trial, "http_sample", lambda host: http())
    monkeypatch.setattr(trial, "infrastructure_sample", lambda *args: infra())
    sampler = trial.Sampler(trial.HOST, 0.01, 1)
    sampler.start()
    assert sampler.http_ready.is_set() and sampler.samples["http"]
    data = sampler.finish(0)
    assert data["http"][0]["ok"] is True


def test_source_owner_rechecked_before_write(monkeypatch):
    instance, calls = setup(monkeypatch, execute=True)
    owners = iter([domain(), domain(trial.WORKERS["B"])])
    monkeypatch.setattr(instance, "domain", lambda: next(owners))
    with pytest.raises(trial.Refused, match="trial_source_owner_changed"):
        instance.execute()
    assert not any(kw.get("method") == "PUT" for _, kw in calls)


@pytest.mark.parametrize("host", ["chat.padiem.net", "chat-com2.padiem.net", "chat-cutover-test.padiem.net.evil.invalid"])
def test_nontrial_hostname_fails_before_network(host):
    instance = trial.Trial(arguments(host=host), {"CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE})
    with pytest.raises(trial.Refused, match="trial_host_required"):
        instance.execute()


def test_execute_needs_exact_confirmation():
    instance = trial.Trial(arguments(execute=True, confirmation="yes"), {"CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE})
    with pytest.raises(trial.Refused, match="confirmation_mismatch"):
        instance.execute()


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_observation_window_is_refused(value):
    instance = trial.Trial(arguments(observe_seconds=value), {"CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE})
    with pytest.raises(trial.Refused, match="measurement_interval_invalid"):
        instance.validate()


@pytest.mark.parametrize("change", [dict(zone_id="d" * 32), dict(service="padiem-chat"),
                                  dict(enabled=False), dict(previews_enabled=True)])
def test_wrong_zone_production_worker_and_preview_scope_refused(monkeypatch, change):
    instance = trial.Trial(arguments(), {"CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE})
    monkeypatch.setattr(instance.api, "cf", lambda *a, **kw: [domain(**change)])
    with pytest.raises(trial.Refused, match="trial_domain_scope_mismatch"):
        instance.domain()


def test_switch_put_once_with_expected_payload(monkeypatch):
    instance, calls = setup(monkeypatch, execute=True)
    instance.execute()
    puts = [(path, kwargs) for path, kwargs in calls if kwargs.get("method") == "PUT"]
    assert puts == [("/workers/domains", {"method": "PUT", "payload": {
        "hostname": trial.HOST, "service": trial.WORKERS["B"], "zone_id": ZONE,
        "enabled": True, "previews_enabled": False,
    }})]
    assert instance.result["outcome"] == "OBSERVED_TARGET"
    assert instance.result["measurement"]["first_target_response_seconds"] == 0.2


def test_rollback_put_once_to_a(monkeypatch):
    instance, calls = setup(monkeypatch, "rollback", True)
    instance.execute()
    puts = [kwargs for _, kwargs in calls if kwargs.get("method") == "PUT"]
    assert len(puts) == 1 and puts[0]["payload"]["service"] == trial.WORKERS["A"]
    # Fixture sampler still says B: identity mismatch must not claim recovery.
    assert instance.result["outcome"] == "STOP_REVIEW_REQUIRED"


def test_put_error_recovers_original_and_keeps_sampling(monkeypatch):
    instance, calls = setup(monkeypatch, execute=True)
    original = instance.api.cf
    def cf(path, **kwargs):
        if kwargs.get("method") == "PUT" and kwargs["payload"]["service"] == trial.WORKERS["B"]:
            calls.append((path, kwargs))
            raise trial.Refused("transport_failed")
        return original(path, **kwargs)
    monkeypatch.setattr(instance.api, "cf", cf)
    instance.execute()
    puts = [kw["payload"]["service"] for _, kw in calls if kw.get("method") == "PUT"]
    assert puts == [trial.WORKERS["B"], trial.WORKERS["A"]]
    assert instance.result["owner_state"] == trial.WORKERS["A"]
    assert instance.result["samples"] is not None
    assert instance.result["outcome"] == "STOP_REVIEW_REQUIRED"


def test_failed_immediate_readback_cannot_become_success(monkeypatch):
    instance, _ = setup(monkeypatch, execute=True)
    original = instance.domain
    count = 0
    def domain_with_temporary_failure():
        nonlocal count
        count += 1
        if count == 3:
            raise trial.Refused("transport_failed")
        return original()
    monkeypatch.setattr(instance, "domain", domain_with_temporary_failure)
    instance.execute()
    assert instance.result["owner_after_matches"] is True
    assert instance.result["error_code"] == "immediate_readback_unverified"
    assert instance.result["outcome"] == "STOP_REVIEW_REQUIRED"


def test_observer_starts_before_put(monkeypatch):
    instance, _ = setup(monkeypatch, execute=True)
    observed = []
    class Recorder(FakeSampler):
        def start(self):
            super().start()
            observed.append("sample_started")
        def finish(self, seconds):
            observed.append("sample_finished")
            return super().finish(seconds)
    original = instance.api.cf
    def cf(path, **kwargs):
        if kwargs.get("method") == "PUT":
            observed.append("put")
        return original(path, **kwargs)
    monkeypatch.setattr(trial, "Sampler", Recorder)
    monkeypatch.setattr(instance.api, "cf", cf)
    instance.execute()
    assert observed == ["sample_started", "put", "sample_finished"]


def test_http_probe_never_retains_untrusted_response(monkeypatch):
    monkeypatch.setattr(trial, "request", lambda *a, **kw: (200, {}, json.dumps({"worker": PRIVATE}).encode()))
    result = trial.http_sample(trial.HOST)
    assert result["ok"] is False and PRIVATE not in json.dumps(result)


def test_measurement_reports_resolution_and_cert_uncertainty():
    samples = {"http": [dict(http("A"), start_seconds=0, end_seconds=0.1),
                         dict(ok=False, status=503, identity=None, start_seconds=0.3, end_seconds=0.4),
                         dict(http("B"), start_seconds=0.6, end_seconds=0.7)],
               "infrastructure": [dict(infra(), start_seconds=0, end_seconds=0.2),
                                  dict(infra(), certificate_sha256="d" * 64, dns_answers=["192.0.2.2"], start_seconds=0.6, end_seconds=0.8)]}
    result = trial.measurement(samples, infra(), "B", 0.2)
    assert result["http_failed_samples"] == 1
    assert result["http_sample_gap_max_seconds"] == 0.3
    assert result["first_target_response_seconds"] == pytest.approx(0.5)
    assert result["http_failures"][0]["recovery_bracket_seconds"] == pytest.approx(0.6)
    assert result["tls_first_observed_certificate_change_seconds"] == pytest.approx(0.6)
    assert result["certificate_reissuance"] == "NOT_ESTABLISHED_BY_FINGERPRINT_SAMPLING"


def test_infrastructure_keeps_certificate_validity_without_raw_certificate(monkeypatch):
    class TLS:
        def getpeercert(self, binary_form=False):
            return b"synthetic-public-certificate" if binary_form else {
                "notBefore": "Oct  1 00:00:00 2026 GMT", "notAfter": "Dec 30 00:00:00 2026 GMT"}
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(0, 0, 0, "", ("192.0.2.1", 443))])
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: nullcontext(object()))
    monkeypatch.setattr(trial.ssl, "create_default_context", lambda: SimpleNamespace(
        wrap_socket=lambda *a, **kw: nullcontext(TLS())))
    result = trial.infrastructure_sample(trial.HOST, 1)
    assert result["tls_ok"] is True
    assert result["certificate_not_before_utc"] == "2026-10-01T00:00:00+00:00"
    assert result["certificate_not_after_utc"] == "2026-12-30T00:00:00+00:00"
    assert "synthetic-public-certificate" not in json.dumps(result)


def test_new_validity_observation_is_not_claimed_as_issuance():
    changed = dict(infra(), certificate_not_before_utc="2026-10-31T00:00:00+00:00",
                   certificate_sha256="d" * 64, start_seconds=1, end_seconds=2,
                   observed_utc="2026-10-31T01:00:02+00:00")
    result = trial.measurement({"http": [], "infrastructure": [changed]}, infra(), "B", 0.5)
    assert result["tls_first_observed_newer_not_before_seconds"] == 1.5
    assert result["tls_first_observed_newer_not_before_utc"] == changed["observed_utc"]
    assert result["tls_first_success_after_put_utc"] == changed["observed_utc"]
    assert result["certificate_reissuance"] == "NOT_ESTABLISHED_BY_FINGERPRINT_SAMPLING"


def test_cli_error_preserves_safe_result_and_never_prints_secret(monkeypatch, tmp_path, capsys):
    destination = tmp_path / "result.json"
    def execute(self):
        self.result["put_attempts"] = 1
        self.result["put_outcome"] = "UNKNOWN"
        raise RuntimeError(PRIVATE)
    monkeypatch.setattr(trial.Trial, "execute", execute)
    assert trial.main(["switch", "--target-sha", SHA, "--out", str(destination)]) == 2
    data = destination.read_text()
    assert PRIVATE not in data + capsys.readouterr().out
    assert json.loads(data)["put_attempts"] == 1


def test_existing_output_refuses_before_execution(monkeypatch, tmp_path):
    destination = tmp_path / "result.json"
    destination.write_text("preserve")
    monkeypatch.setattr(trial.Trial, "execute", lambda self: pytest.fail("must not execute"))
    assert trial.main(["switch", "--target-sha", SHA, "--out", str(destination)]) == 2
    assert destination.read_text() == "preserve"


def test_put_captures_http_status_and_complete_error_envelope(monkeypatch):
    account = "c" * 32
    token = "synthetic-private-token"
    instance = trial.Trial(arguments(execute=True), {
        "CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE,
        "CLOUDFLARE_ACCOUNT_ID": account, "CLOUDFLARE_API_TOKEN": token,
    })
    envelope = {"success": False, "errors": [{"code": 100, "message": "domain already attached"}],
                "messages": [{"code": 7, "message": "detail"}], "result": None}
    calls = []
    def request(url, **kw):
        calls.append((url, kw))
        return 409, {"ignored": "headers"}, json.dumps(envelope).encode()
    monkeypatch.setattr(trial, "request", request)
    with pytest.raises(trial.Refused, match="cloudflare_put_not_successful"):
        instance.mutate_domain("PUT", "/workers/domains", {"service": trial.WORKERS["B"]})
    assert instance.result["api_response"] == {"http_status": 409, "body": envelope}
    assert len(calls) == 1 and calls[0][1]["method"] == "PUT"
    assert token not in json.dumps(instance.result["api_response"])

def test_delete_empty_response_is_recorded_and_accepted(monkeypatch):
    instance = trial.Trial(arguments(execute=True), {
        "CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE,
        "CLOUDFLARE_ACCOUNT_ID": "c" * 32, "CLOUDFLARE_API_TOKEN": "synthetic",
    })
    monkeypatch.setattr(trial, "request", lambda *a, **kw: (200, {}, b""))
    instance.mutate_domain("DELETE", "/workers/domains/" + "e" * 40, None)
    assert instance.result["api_responses"] == [
        {"method": "DELETE", "http_status": 200, "body": {"non_json_body": ""}}]


def test_put_response_scrubs_credential_echo(monkeypatch):
    token = "synthetic-sensitive-token"
    instance = trial.Trial(arguments(execute=True), {
        "CHAT_CUTOVER_TRIAL_ZONE_ID": ZONE,
        "CLOUDFLARE_ACCOUNT_ID": "c" * 32, "CLOUDFLARE_API_TOKEN": token,
    })
    monkeypatch.setattr(trial, "request", lambda *a, **kw: (
        403, {}, json.dumps({"success": False, "errors": [{"code": 1, "message": token}],
                             "messages": [], "result": None}).encode()))
    with pytest.raises(trial.Refused):
        instance.mutate_domain("PUT", "/workers/domains", {"service": trial.WORKERS["B"]})
    assert token not in json.dumps(instance.result["api_response"])
