"""Cloudflare Chat crons versus the COM2 systemd timer package, 1:1.

The cutover replaces the Worker's scheduled lane with a host timer, so the two
sides must stay matched. This test reads only what the repository declares --

* the ``crons`` entries of the Chat wrangler configs,
* the Worker's ``scheduled()`` dispatch,
* the units and profiles under ``deploy/host-com2/cron/``,

-- and fails when any of them drifts. The deployed trigger is dashboard-owned
and cannot be read here; ``cron_parity.json`` records that and the installer
still refuses to render without the period taken from the dashboard.

No host is contacted, nothing is installed and no timer is started.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT = ROOT / "apps" / "padiem-chat"
CRON = ROOT / "deploy" / "host-com2" / "cron"
MANIFEST = json.loads((CRON / "cron_parity.json").read_text(encoding="utf-8"))
JOBS = MANIFEST["jobs"]


def worker_crons() -> list[tuple[str, str]]:
    """Every ``crons = [...]`` value in the Chat wrangler configs."""

    found: list[tuple[str, str]] = []
    for config in sorted(CHAT.glob("wrangler*.toml")):
        text = config.read_text(encoding="utf-8")
        # Matches multi-line arrays: [^\]] spans newlines on purpose.
        match = re.search(r"^crons\s*=\s*\[(.*?)\]", text, re.M | re.S)
        if match is None:
            continue
        found.extend(
            (config.name, value) for value in re.findall(r'"([^"]+)"', match.group(1))
        )
    return found


def scheduled_calls() -> set[str]:
    """The functions ``Default.scheduled()`` actually dispatches to."""

    text = (CHAT / "worker.py").read_text(encoding="utf-8")
    body = re.search(r"async def scheduled\(.*?\n\n", text, re.S)
    assert body, "worker.py has no scheduled handler"
    return set(re.findall(r"await\s+(\w+)\(", body.group(0)))


def test_the_manifest_is_one_job_per_timer():
    timers = {path.name for path in CRON.glob("*.timer.template")}
    services = {path.name for path in CRON.glob("*.service.template")}

    assert {job["timer_template"] for job in JOBS} == timers
    assert {job["service_template"] for job in JOBS} == services
    assert len({job["unit_prefix"] for job in JOBS}) == len(JOBS)


def test_every_source_declared_worker_cron_maps_to_a_timer():
    declared = worker_crons()
    mapped = [job["worker_cron"] for job in JOBS if job["worker_cron"]]

    # A Worker cron with no timer would keep running after the cutover; a timer
    # with no Worker cron would be a second scheduler nobody asked for.
    assert sorted(cron for _name, cron in declared) == sorted(mapped), (
        f"declared={declared} mapped={mapped}"
    )


def test_the_scheduled_handler_dispatches_only_mapped_jobs():
    handlers = {job["worker_handler"] for job in JOBS}
    assert scheduled_calls() == handlers


def test_the_timer_reads_the_expression_as_utc():
    assert MANIFEST["timezone"] == "UTC"
    for job in JOBS:
        timer = (CRON / job["timer_template"]).read_text(encoding="utf-8")
        # Cloudflare cron expressions are UTC. Without this, systemd evaluates
        # the same expression in the host's local time (KST, +9h).
        assert "Timezone=UTC" in timer
        calendars = [
            line for line in timer.splitlines() if line.startswith("OnCalendar=")
        ]
        # The period is dashboard-owned, so no literal may be baked in.
        assert calendars == ["OnCalendar=@CRON_SCHEDULE@"]


def test_the_profiles_use_the_manifest_unit_prefix():
    units = {}
    for profile in ("staging", "production"):
        text = (CRON / "profiles" / f"{profile}.conf").read_text(encoding="utf-8")
        match = re.search(r"^UNIT_NAME=(\S+)$", text, re.M)
        assert match, profile
        units[profile] = match.group(1)
        assert units[profile].startswith(tuple(job["unit_prefix"] for job in JOBS))
    assert units["staging"] != units["production"]


def test_the_service_runs_the_same_local_entry():
    source = (CHAT / "app" / "local_cron.py").read_text(encoding="utf-8")
    assert "def run_once" in source and "def main(" in source

    runner = (CRON / "run-cron.sh").read_text(encoding="utf-8")
    assert "-m app.local_cron --once" in runner
    for job in JOBS:
        assert job["local_entry"] == "app.local_cron"
        assert job["local_entry"] in job["command"]


def test_the_package_states_the_utc_rule():
    readme = (CRON / "README.md").read_text(encoding="utf-8")
    assert "Timezone=UTC" in readme
    assert "dashboard" in readme
