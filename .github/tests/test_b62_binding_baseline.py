"""#5223: the reviewed Worker binding baseline contract.

The Owner D1 release preparation used to pin the live binding set with a
binding count. These tests pin the replacement: a reviewed name+type
baseline, compared by name and type, with bounded diagnostics.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / ".github/scripts"
sys.path.insert(0, str(SCRIPT_DIR))
spec = importlib.util.spec_from_file_location(
    "b62_binding_baseline", SCRIPT_DIR / "b62_binding_baseline.py"
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BASELINE_DIR = ROOT / ".github/binding_baselines"


def _payload(entries):
    return {"success": True, "result": {"bindings": [
        {"name": name, "type": kind} for name, kind in entries
    ]}}


def test_every_supported_worker_has_a_committed_baseline():
    for worker in mod.SUPPORTED_WORKERS:
        path = mod.baseline_path(worker)
        assert path.is_file(), worker
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["worker"] == worker
        assert payload["bindings"]


def test_a_baseline_entry_carries_a_name_and_a_type_and_nothing_else():
    for worker in mod.SUPPORTED_WORKERS:
        payload = json.loads(mod.baseline_path(worker).read_text(encoding="utf-8"))
        for entry in payload["bindings"]:
            assert set(entry) == {"name", "type"}, entry
            assert isinstance(entry["name"], str) and entry["name"]
            assert isinstance(entry["type"], str) and entry["type"]


def test_no_baseline_carries_a_value_a_database_id_or_a_secret():
    """A baseline states an identity and a kind, never a value."""

    allowed_keys = {
        "worker", "reviewed_utc", "source_served_version", "bindings",
        "name", "type",
    }

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key in allowed_keys, key
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            # A secret is never short. The served version id is recorded on
            # purpose as provenance and is not a credential.
            assert len(node) <= 64, node

    for worker in mod.SUPPORTED_WORKERS:
        payload = json.loads(mod.baseline_path(worker).read_text(encoding="utf-8"))
        walk(payload)
        # The binding identity is a name and a kind; nothing else is carried.
        for entry in payload["bindings"]:
            assert set(entry) == {"name", "type"}


def test_a_baseline_has_no_duplicate_binding_names():
    for worker in mod.SUPPORTED_WORKERS:
        expected = mod.load_baseline(worker)
        assert len(expected) == len(set(expected))


def test_the_comparison_is_by_name_and_type():
    expected = {"A": "plain_text", "B": "d1"}
    assert mod.compare_entries([("A", "plain_text"), ("B", "d1")], expected) == ([], [])
    # A different type is a drift of that binding.
    missing, unexpected = mod.compare_entries([("A", "plain_text"), ("B", "plain_text")], expected)
    assert missing == ["B"] and unexpected == []
    # An unapproved binding is an unexpected binding.
    missing, unexpected = mod.compare_entries(
        [("A", "plain_text"), ("B", "d1"), ("C", "plain_text")], expected
    )
    assert missing == [] and unexpected == ["C"]
    # A missing approved binding is a missing binding.
    missing, unexpected = mod.compare_entries([("A", "plain_text")], expected)
    assert missing == ["B"] and unexpected == []


def test_a_matching_live_set_passes_and_a_drift_fails_closed():
    expected = mod.load_baseline("padiem-chat")
    payload = _payload(sorted(expected.items()))
    assert mod.assert_matches_baseline("padiem-chat", payload) == len(expected)
    payload["result"]["bindings"].append({"name": "UNAPPROVED", "type": "plain_text"})
    with pytest.raises(mod.BindingBaselineError) as excinfo:
        mod.assert_matches_baseline("padiem-chat", payload)
    assert "BINDING_SET_DRIFT" in str(excinfo.value)


def test_a_version_payload_is_accepted_as_well_as_a_settings_payload():
    expected = mod.load_baseline("padiem-ai-engine")
    entries = sorted(expected.items())
    version_payload = {"success": True, "result": {"id": "v1", "resources": {
        "bindings": [{"name": n, "type": t} for n, t in entries]}}}
    assert mod.assert_matches_baseline("padiem-ai-engine", version_payload) == len(expected)


def test_the_keyed_version_binding_shape_is_accepted():
    expected = mod.load_baseline("padiem-chat")
    keyed = {"success": True, "result": {"id": "v1", "resources": {
        "bindings": {n: {"type": t} for n, t in sorted(expected.items())}}}}
    assert mod.assert_matches_baseline("padiem-chat", keyed) == len(expected)


def test_a_malformed_payload_fails_closed():
    for payload in (
        {"success": False, "result": {}},
        {"success": True, "result": {}},
        {"success": True, "result": {"bindings": "not-a-list"}},
        {"success": True, "result": {"bindings": [{"name": "A"}]}},
        {"success": True, "result": {"bindings": [{"type": "plain_text"}]}},
    ):
        with pytest.raises(mod.BindingBaselineError):
            mod.assert_matches_baseline("padiem-chat", payload)


def test_an_unknown_worker_is_refused():
    with pytest.raises(mod.BindingBaselineError):
        mod.baseline_path("some-other-worker")


def test_the_cli_reports_a_bounded_verdict_without_naming_a_binding(tmp_path, capsys):
    expected = mod.load_baseline("padiem-chat")
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_payload(sorted(expected.items()))), encoding="utf-8")
    assert mod.main(["--worker", "padiem-chat", "--payload", str(good)]) == 0
    out = capsys.readouterr().out
    assert "BINDING_BASELINE=PASS" in out
    assert "BINDING_BASELINE_VALUES_EMITTED=0" in out
    for name in expected:
        assert name not in out

    drift = tmp_path / "drift.json"
    entries = sorted(expected.items())
    payload = _payload(entries)
    payload["result"]["bindings"].append({"name": "UNAPPROVED", "type": "plain_text"})
    drift.write_text(json.dumps(payload), encoding="utf-8")
    assert mod.main(["--worker", "padiem-chat", "--payload", str(drift)]) == 2
    err = capsys.readouterr().err
    assert "BINDING_SET_DRIFT" in err
    assert "MISSING=0" in err and "UNEXPECTED=1" in err
    # The bounded diagnostic never names a binding.
    assert "UNAPPROVED" not in err
    for name in expected:
        assert name not in err
