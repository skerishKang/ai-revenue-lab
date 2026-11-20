"""#8043: cooldown bookkeeping for a pairing tag carried by a presence beat."""
from __future__ import annotations

PAIRING_TAG_RECARRY_SECONDS = 300.0


def should_carry(reported: dict[str, float], tag: str, now: float) -> bool:
    """A tag travels until carried, then again once the cooldown has elapsed."""
    last = reported.get(tag)
    return last is None or (now - last) >= PAIRING_TAG_RECARRY_SECONDS


def mark_carried(reported: dict[str, float], tags: list[str], now: float) -> None:
    """Acknowledge carried tags with the time of the beat the server took."""
    for tag in tags:
        reported[tag] = now
