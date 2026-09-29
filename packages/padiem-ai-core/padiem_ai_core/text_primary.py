"""Canonical platform text-primary model declaration (#3199 follow-up).

Owner decision (2026-09-29): the platform **text-primary** model is **Space
Bunny Alpha** on the keyless Kilo Gateway free lane. SenseNova is explicitly
**not** the text primary; it remains a registered provider route only.

This module is the single canonical source for the text-primary identity:

    TEXT_PRIMARY_PROVIDER_ID     = "kilo"
    TEXT_PRIMARY_MODEL_ID        = "kilo/stealth-space-bunny-alpha"
    TEXT_PRIMARY_UPSTREAM_MODEL  = "stealth/space-bunny-alpha"

The primary-text production smokes import ``TEXT_PRIMARY_MODEL_ID`` from here
(``apps/padiem-ai-engine/scripts/a9_production_smoke.py`` and
``a12_stream_replay_production_smoke.py``), so their pinned model can never
drift from this declaration by copy-paste. The Business 14 catalog registers
the same route in ``apps/korean-ai-platform/app/pilot/kilo_provider.py``; the
parity between the two authorities is asserted by
``.github/tests/test_b54_text_primary_route_parity.py``.

Scope locks:

* The **vision** primary stays UNDECIDED. Space Bunny Alpha advertises
  image/video input upstream, but this declaration performs no vision or
  multimodal routing and must not be read as a vision assignment.
* The B14 ``b14/auto`` fixed compatibility chain is not this authority and is
  deliberately untouched here.

Stdlib-only, network-free, execution-free constant declaration.
"""

from __future__ import annotations

TEXT_PRIMARY_PROVIDER_ID = "kilo"
TEXT_PRIMARY_MODEL_ID = "kilo/stealth-space-bunny-alpha"
TEXT_PRIMARY_UPSTREAM_MODEL = "stealth/space-bunny-alpha"

# The vision role remains undecided (owner has not selected a vision primary).
# Nothing in this module assigns or activates image/video/model routing.
VISION_PRIMARY_DECISION = "UNDECIDED"
