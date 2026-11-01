"""The connector release version rule: one number, in both homes, actually bumped.

The connector carries its version in two places — ``pyproject.toml`` for the
package and ``kagent.__version__`` for the runtime. The #6621 read-envelope
change plus the #3782 browser lane ride one connector version, so the release
pins the two homes together and above the previously installed 0.2.0
(05_RELEASE_ROLLBACK_POLICY.md: semver where external consumers exist).
"""
from __future__ import annotations

import re
from pathlib import Path

import kagent

APP_ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (APP_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml must carry a version line"
    return match.group(1)


def test_the_two_version_homes_agree():
    assert _pyproject_version() == kagent.__version__


def test_the_release_version_is_semver_and_above_the_installed_0_2_0():
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", _pyproject_version())
    assert match, "the connector version must be X.Y.Z (semver)"
    triple = tuple(int(part) for part in match.groups())
    assert triple == (0, 3, 0)
    assert triple > (0, 2, 0)
