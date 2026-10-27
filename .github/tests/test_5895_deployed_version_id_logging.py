"""#5895: every production deploy gate must name the version it promoted.

Run 40448053678 is the reason: the Chat gate put ``DEPLOYED_VERSION_ID`` into
``GITHUB_ENV`` only, so the finished run log never said which Worker version it
had just promoted. A version id is not a secret. One uniform, grep-able line
belongs on stdout and in the step summary of every mutating path, and the same
line belongs on the rollback paths, because a rollback that nobody can name is
evidence nobody can read.

One assertion, three gates, both mutation classes: the deploy job and the
rollback job of the Chat, Engine and B14 production gates each carry the line.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

MARKER = "DEPLOYED_VERSION_ID=${"

# gate -> workflow, (deploy job start, end) and (rollback job start, end); a
# missing end means the rest of the file. The Chat gate's in-job auto-rollback
# step sits inside the deploy region, so the deploy half covers both of its
# mutation paths.
GATES = {
    "chat": (
        ".github/workflows/b62-production-code-deploy-gate.yml",
        ("  deploy-production-code:", "  rollback-production-code:"),
        ("  rollback-production-code:", "  owner-d1-release-preflight:"),
    ),
    "engine": (
        ".github/workflows/b54-engine-production-deploy-gate.yml",
        ("  deploy-production-engine:", "  smoke-idempotency:"),
        ("  rollback-production-engine:", None),
    ),
    "b14": (
        ".github/workflows/b14-production-deploy-gate.yml",
        ("  deploy-production-b14:", "  retire-openrouter-secret:"),
        ("  rollback-production-b14:", "  promote-verified-private-candidate-b14:"),
    ),
}


def _regions(name: str) -> tuple[str, str]:
    path, (deploy_start, deploy_end), (rollback_start, rollback_end) = GATES[name]
    text = (ROOT / path).read_text(encoding="utf-8", newline=None)
    yaml.safe_load(text)
    deploy = text[text.index(deploy_start):text.index(deploy_end)]
    start = text.index(rollback_start)
    rollback = text[start:] if rollback_end is None else text[start:text.index(rollback_end)]
    return deploy, rollback


def test_every_mutating_gate_path_logs_one_uniform_deployed_version_line() -> None:
    for name in GATES:
        for label, region in zip(("deploy", "rollback"), _regions(name)):
            lines = [line.strip() for line in region.splitlines() if MARKER in line]
            assert lines, f"{name} {label} path never names the version it put into service"
            # The line has to reach stdout AND the step summary, and it has to
            # interpolate the resolved id rather than carry a literal one.
            assert any(
                line.startswith("echo ") and "GITHUB_STEP_SUMMARY" in line
                for line in lines
            ), (name, label, lines)
            assert not re.search(r"DEPLOYED_VERSION_ID=[0-9a-fA-F][0-9a-fA-F-]{7,}", region), (name, label)
