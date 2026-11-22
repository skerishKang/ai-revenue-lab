"""Parsed views for the connector version compatibility display contracts.

Raw file reads live here. Tests receive the parsed presentation-variant tuple,
parsed key counts and source fragments. The shared ``claw_static`` and
``locale_bundle`` helpers are reused for the underlying reads.
"""
from __future__ import annotations

import re

import locale_bundle

from _support.claw_static import sheet


def handoff_source() -> str:
    return sheet("claw-local-handoff.js")


def device_manager_source() -> str:
    return sheet("claw-device-manager.js")


def presentation_variants() -> tuple[str, ...]:
    """The JS presentation-variant tuple, parsed from its frozen declaration."""
    source = handoff_source()
    match = re.search(
        r"PRESENTATION_VARIANTS = Object\.freeze\(\[([^\]]*)\]\)", source
    )
    assert match is not None
    return tuple(item.strip().strip('"') for item in match.group(1).split(","))


def locale_key_count(key: str) -> int:
    """Occurrences of a quoted locale key in the merged locale source."""
    return locale_bundle.SOURCE.read_text(encoding="utf-8").count(f'"{key}"')


def device_manager_key_count(key: str) -> int:
    """Occurrences of a `key: "` declaration in the device-manager module."""
    return len(re.findall(rf"\b{re.escape(key)}: \"", device_manager_source()))


def device_manager_has(fragment: str) -> bool:
    return fragment in device_manager_source()
