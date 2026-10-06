"""Canonical platform model-primary declaration.

Owner successor selection (2026-10-06, follow-up to #3568/#3569): the Padiem
Plus TEXT primary is Ling 3.1 Flash on the Kilo gateway
(kilo/inclusionai-ling-3.1-flash, upstream inclusionai/ling-3.1-flash),
verified live (HTTP 200, zero-cost free lane, context 262,144 / max output
32,768). Policy v2: model lanes authenticate through Secrets Store bindings;
the keyless-preference era is retired.

- text primary: Ling 3.1 Flash (selected and verified);
- vision primary: pending explicit successor selection — Ling 3.1 Flash is
  text-only, so image work stays fail closed (Policy A);
- no secondary model;
- no fallback;
- no runtime execution, network I/O, or secret access.

Business 14 provider registrations may retain historical/manual route metadata,
but none becomes a Padiem product primary or silent fallback through this file.
"""

from __future__ import annotations

TEXT_PRIMARY_DECISION = "Owner successor selection 2026-10-06 (Ling 3.1 Flash, Kilo gateway)"
TEXT_PRIMARY_PROVIDER_ID = "kilo"
TEXT_PRIMARY_MODEL_ID = "kilo/inclusionai-ling-3.1-flash"
TEXT_PRIMARY_UPSTREAM_MODEL = "inclusionai/ling-3.1-flash"

VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"
VISION_PRIMARY_PROVIDER_ID = None
VISION_PRIMARY_MODEL_ID = None
VISION_PRIMARY_UPSTREAM_MODEL = None

TEXT_SECONDARY_MODEL_ID = None
TEXT_FALLBACK_ENABLED = False

VISION_FALLBACK_MODEL_ID = None
VISION_FALLBACK_DECISION = "UNDECIDED"

VIDEO_PRIMARY_DECISION = "UNDECIDED"
