#!/usr/bin/env python3
"""Staging-only custom-domain measurement; default is read-only dry-run.

This script does not create/deploy Workers or attach a missing hostname. Each
explicit switch/rollback issues at most one PUT. An uncertain write is never
retried or automatically reversed. Only fixed codes and bounded identity
metadata enter the result; tokens and arbitrary response bodies never do.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_com2_cutover_gate import Gate, Refused, require, request  # noqa: E402

HOST = "chat-cutover-test.padiem.net"
WORKERS = {"A": "padiem-chat-cutover-trial-a", "B": "padiem-chat-cutover-trial-b"}
SCHEMA = "chat-domain-move-trial/v1"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def http_sample(host):
    """The only returned body field is the exact allowlisted fixture identity."""
    try:
        status, headers, raw = request("https://" + host + "/__cutover_trial")
        body = json.loads(raw)
        identity = body.get("worker") if body.get("trial") == "chat-domain-move" else None
        lower = {key.lower(): value for key, value in headers.items()}
        ok = status == 200 and identity in WORKERS and "no-store" in lower.get("cache-control", "")
        return {"status": status, "identity": identity if identity in WORKERS else None, "ok": ok}
    except Exception:
        return {"status": None, "identity": None, "ok": False}


def infrastructure_sample(host, timeout):
    result = {"dns_ok": False, "dns_answers": [], "tls_ok": False, "certificate_sha256": None,
              "certificate_not_before_utc": None, "certificate_not_after_utc": None}
    try:
        result["dns_answers"] = sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        result["dns_ok"] = bool(result["dns_answers"])
    except OSError:
        pass
    try:
        with socket.create_connection((host, 443), timeout=timeout) as connection:
            with ssl.create_default_context().wrap_socket(connection, server_hostname=host) as tls:
                result["certificate_sha256"] = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
                result["tls_ok"] = True
                details = tls.getpeercert()
                for source, target in (("notBefore", "certificate_not_before_utc"),
                                       ("notAfter", "certificate_not_after_utc")):
                    if details.get(source):
                        try:
                            stamp = ssl.cert_time_to_seconds(details[source])
                            result[target] = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
                        except (ValueError, TypeError, OverflowError):
                            pass
    except (OSError, ValueError):
        pass
    return result


class Sampler:
    """HTTP stays observable while the PUT or DNS/TLS checks are waiting."""
    def __init__(self, host, interval, timeout):
        self.host, self.interval, self.timeout = host, interval, timeout
        self.samples = {"http": [], "infrastructure": []}
        self.stop_event = threading.Event()
        self.http_ready = threading.Event()
        self.threads = []
        self.epoch = time.monotonic()

    def _collect(self, name, probe):
        while not self.stop_event.is_set():
            started = time.monotonic()
            sample = probe()
            sample.update(start_seconds=started - self.epoch, end_seconds=time.monotonic() - self.epoch,
                          observed_utc=utc_now())
            self.samples[name].append(sample)
            if name == "http":
                self.http_ready.set()
            if self.stop_event.wait(self.interval):
                break

    def start(self):
        for name, probe in (
            ("http", lambda: http_sample(self.host)),
            ("infrastructure", lambda: infrastructure_sample(self.host, self.timeout)),
        ):
            thread = threading.Thread(target=self._collect, args=(name, probe), daemon=True)
            self.threads.append(thread)
            thread.start()
        # Have one actual HTTP observation before the domain write begins.
        self.http_ready.wait()

    def finish(self, seconds):
        self.stop_event.wait(seconds)
        self.stop_event.set()
        for thread in self.threads:
            thread.join()
        return self.samples


def measurement(samples, baseline, target, put_start):
    http = samples["http"]
    infra = samples["infrastructure"]
    failed = [row for row in http if not row["ok"]]
    target_rows = [row for row in http if row["ok"] and row["identity"] == target and row["end_seconds"] >= put_start]
    gaps = [right["start_seconds"] - left["start_seconds"] for left, right in zip(http, http[1:])]
    first_target = target_rows[0]["end_seconds"] - put_start if target_rows else None
    failures = []
    for index, row in enumerate(http):
        if row["ok"]:
            continue
        previous = next((x for x in reversed(http[:index]) if x["ok"]), None)
        following = next((x for x in http[index + 1:] if x["ok"]), None)
        failures.append({"at_seconds": row["end_seconds"], "recovery_bracket_seconds":
                         following["end_seconds"] - previous["end_seconds"] if previous and following else None})
    def change_seconds(field, success_field):
        rows = [x for x in infra if x[success_field] and x[field] != baseline[field] and x["end_seconds"] >= put_start]
        return rows[0]["end_seconds"] - put_start if rows else None
    tls_success = [x for x in infra if x["tls_ok"] and x["end_seconds"] >= put_start]
    old_not_before = baseline.get("certificate_not_before_utc")
    newer_validity = [x for x in tls_success if old_not_before and x.get("certificate_not_before_utc") and
                     x["certificate_not_before_utc"] > old_not_before]
    changed_certificate = [x for x in tls_success if x["certificate_sha256"] != baseline["certificate_sha256"]]
    return {
        "http_sample_count": len(http), "http_failed_samples": len(failed),
        "http_sample_gap_max_seconds": max(gaps, default=0),
        "http_failure_observation_span_seconds": failed[-1]["end_seconds"] - failed[0]["end_seconds"] if failed else None,
        "http_failures": failures, "first_target_response_seconds": first_target,
        "dns_first_observed_change_seconds": change_seconds("dns_answers", "dns_ok"),
        "tls_first_observed_certificate_change_seconds": change_seconds("certificate_sha256", "tls_ok"),
        "tls_first_success_after_put_utc": tls_success[0].get("observed_utc") if tls_success else None,
        "tls_first_success_after_put_seconds": tls_success[0]["end_seconds"] - put_start if tls_success else None,
        "tls_first_observed_certificate_change_utc": changed_certificate[0].get("observed_utc") if changed_certificate else None,
        "tls_first_observed_newer_not_before_utc": newer_validity[0].get("observed_utc") if newer_validity else None,
        "tls_first_observed_newer_not_before_seconds": newer_validity[0]["end_seconds"] - put_start if newer_validity else None,
        "dns_failed_samples": sum(not x["dns_ok"] for x in infra),
        "tls_failed_samples": sum(not x["tls_ok"] for x in infra),
        "certificate_reissuance": "NOT_ESTABLISHED_BY_FINGERPRINT_SAMPLING",
        "continuity_claim": "SAMPLED_FAILURES" if failed else "NO_FAILURE_OBSERVED_AT_RECORDED_RESOLUTION",
    }


class Trial:
    def __init__(self, args, env=None):
        self.args = args
        self.env = dict(os.environ if env is None else env)
        self.env["TARGET_SHA"] = args.target_sha
        self.api = Gate(self.env)
        self.source, self.target = ("A", "B") if args.mode == "switch" else ("B", "A")
        self.result = {
            "schema": SCHEMA, "started_utc": utc_now(), "ended_utc": None,
            "mode": args.mode, "dry_run": not args.execute, "host": HOST,
            "target_sha": args.target_sha, "source_worker": WORKERS[self.source],
            "target_worker": WORKERS[self.target], "outcome": "NOT_RUN",
            "put_attempts": 0, "put_outcome": "NOT_ATTEMPTED", "put_seconds": None,
            "put_started_utc": None, "put_ended_utc": None,
            "owner_before": None, "owner_after": None, "owner_after_matches": None,
            "owner_immediate": None, "owner_immediate_matches": None,
            "owner_immediate_readback_seconds": None,
            "observation_seconds": args.observe_seconds, "interval_seconds": args.interval_seconds,
            "baseline": None, "samples": None, "measurement": None, "error_code": None,
            "planned_change": {"method": "PUT", "endpoint": "/accounts/{account_id}/workers/domains",
                               "hostname": HOST, "service": WORKERS[self.target]},
        }

    def validate(self):
        require(self.args.mode in {"switch", "rollback"}, "trial_mode_invalid")
        require(self.args.host == HOST, "trial_host_required")
        require(bool(re.fullmatch(r"[0-9a-f]{40}", self.args.target_sha)), "sha_invalid")
        require(bool(re.fullmatch(r"[0-9a-f]{32}", self.env.get("CHAT_CUTOVER_TRIAL_ZONE_ID", ""))), "trial_zone_required")
        for value in (self.args.observe_seconds, self.args.interval_seconds, self.args.connect_timeout):
            require(math.isfinite(value) and value > 0, "measurement_interval_invalid")
        if self.args.execute:
            expected = f"{self.args.mode.upper()}_CHAT_DOMAIN_TRIAL_{HOST}_{self.args.target_sha}"
            require(self.args.confirmation == expected, "trial_confirmation_mismatch")

    def domain(self):
        rows = self.api.cf("/workers/domains?hostname=" + HOST)
        matches = [row for row in rows if row.get("hostname") == HOST]
        require(len(matches) == 1, "trial_domain_not_unique")
        row = matches[0]
        require(row.get("service") in WORKERS.values() and row.get("zone_name") == "padiem.net" and
                row.get("zone_id") == self.env["CHAT_CUTOVER_TRIAL_ZONE_ID"] and
                row.get("enabled") is True and row.get("previews_enabled") is False,
                "trial_domain_scope_mismatch")
        return row

    def execute(self):
        self.validate()
        self.api.exact_main()
        self.api.account()
        before = self.domain()
        require(before["service"] == WORKERS[self.source], "trial_source_owner_mismatch")
        self.result["owner_before"] = before["service"]
        baseline_http = http_sample(HOST)
        baseline = infrastructure_sample(HOST, self.args.connect_timeout)
        self.result["baseline"] = {"http": baseline_http, "infrastructure": baseline}
        require(baseline_http["ok"] and baseline_http["identity"] == self.source and
                baseline["dns_ok"] and baseline["tls_ok"], "trial_baseline_unhealthy")
        if not self.args.execute:
            self.result["outcome"] = "READ_ONLY_READY"
            return
        self.api.exact_main()
        require(self.domain()["service"] == WORKERS[self.source], "trial_source_owner_changed")
        sampler = Sampler(HOST, self.args.interval_seconds, self.args.connect_timeout)
        sampler.start()
        started = time.monotonic()
        put_start = started - sampler.epoch
        self.result["put_attempts"] = 1
        self.result["put_outcome"] = "UNKNOWN"
        self.result["put_started_utc"] = utc_now()
        try:
            self.api.cf("/workers/domains", method="PUT", payload={
                "hostname": HOST, "service": WORKERS[self.target],
                "zone_id": before["zone_id"], "enabled": True, "previews_enabled": False,
            })
            self.result["put_outcome"] = "API_SUCCESS"
        except Refused:
            # A timeout or even an error response does not prove no change.
            # Preserve that uncertainty and keep collecting read-only evidence.
            self.result["error_code"] = "put_outcome_unknown"
        finally:
            self.result["put_seconds"] = time.monotonic() - started
            self.result["put_ended_utc"] = utc_now()
            try:
                immediate = self.domain()
                self.result["owner_immediate"] = immediate["service"]
                self.result["owner_immediate_matches"] = immediate["service"] == WORKERS[self.target]
                self.result["owner_immediate_readback_seconds"] = time.monotonic() - started
            except Refused:
                self.result["error_code"] = self.result["error_code"] or "immediate_readback_unverified"
            finally:
                self.result["samples"] = sampler.finish(self.args.observe_seconds)
        try:
            after = self.domain()
            self.result["owner_after"] = after["service"]
            self.result["owner_after_matches"] = after["service"] == WORKERS[self.target]
        except Refused:
            self.result["error_code"] = self.result["error_code"] or "owner_readback_unverified"
        self.result["measurement"] = measurement(self.result["samples"], baseline, self.target, put_start)
        converged = self.result["measurement"]["first_target_response_seconds"] is not None
        passed = self.result["put_outcome"] == "API_SUCCESS" and self.result["owner_after_matches"] is True and converged
        self.result["outcome"] = "OBSERVED_TARGET" if passed else "STOP_REVIEW_REQUIRED"


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("mode", choices=("switch", "rollback"))
    result.add_argument("--host", default=HOST)
    result.add_argument("--target-sha", required=True)
    result.add_argument("--out", required=True, help="new result JSON; existing file is refused")
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="explicit CTO-authorized single PUT")
    mode.add_argument("--dry-run", dest="execute", action="store_false", help="read-only inspection (default)")
    result.set_defaults(execute=False)
    result.add_argument("--confirmation", default="")
    result.add_argument("--observe-seconds", type=float, default=30)
    result.add_argument("--interval-seconds", type=float, default=0.25)
    result.add_argument("--connect-timeout", type=float, default=5)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    trial = Trial(args)
    # Fail on an unwritable/colliding evidence path BEFORE considering a PUT.
    try:
        output = Path(args.out).open("x", encoding="utf-8")
    except OSError:
        print("DOMAIN_TRIAL=REFUSED reason=result_path_unavailable")
        return 2
    try:
        trial.execute()
    except Refused as error:
        trial.result["outcome"] = "REFUSED"
        trial.result["error_code"] = str(error)
    except Exception:
        trial.result["outcome"] = "STOP_REVIEW_REQUIRED"
        trial.result["error_code"] = "unexpected_failure"
    finally:
        trial.result["ended_utc"] = utc_now()
        with output:
            json.dump(trial.result, output, indent=2, sort_keys=True)
            output.write("\n")
    print("DOMAIN_TRIAL=" + trial.result["outcome"])
    if trial.result["outcome"] in {"READ_ONLY_READY", "OBSERVED_TARGET"}:
        return 0
    print("NEXT=inspect_readonly_ownership_no_retry_no_automatic_rollback")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
