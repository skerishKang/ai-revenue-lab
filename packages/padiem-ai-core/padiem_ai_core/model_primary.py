"""Canonical platform model-primary declaration.

The previous Space Bunny text/vision primary is no longer executable after the
owner ended use of that free lane (#3568). A successor is intentionally not
selected in this source slice.

This declaration therefore carries a model-neutral HOLD state:

- text primary: pending explicit successor selection;
- vision primary: pending explicit successor selection;
- no secondary model;
- no fallback;
- no runtime execution, network I/O, or secret access.

Business 14 provider registrations may retain historical/manual route metadata,
but none becomes a Padiem product primary or silent fallback through this file.
"""

from __future__ import annotations

TEXT_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"
TEXT_PRIMARY_PROVIDER_ID = None
TEXT_PRIMARY_MODEL_ID = None
TEXT_PRIMARY_UPSTREAM_MODEL = None

VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"
VISION_PRIMARY_PROVIDER_ID = None
VISION_PRIMARY_MODEL_ID = None
VISION_PRIMARY_UPSTREAM_MODEL = None

TEXT_SECONDARY_MODEL_ID = None
TEXT_FALLBACK_ENABLED = False

VISION_FALLBACK_MODEL_ID = None
VISION_FALLBACK_DECISION = "UNDECIDED"

VIDEO_PRIMARY_DECISION = "UNDECIDED"
