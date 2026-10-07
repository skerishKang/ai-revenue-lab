"""Canonical platform model-primary declaration.

Owner decision 2026-10-07 (#3554) selects the successor in SPLIT roles: the
text role is filled by Agnes 3.0 Flash on the B14 `agnes-ai` provider, and the
vision role stays deliberately unselected.

- text primary: Agnes 3.0 Flash (owner-selected, proven network-free here);
- vision primary: still pending explicit successor selection;
- no secondary model;
- no fallback (a reserve candidate is a review concept, never an executable
  fallback — see #2085 SILENT_FALLBACK=NO);
- no runtime execution, network I/O, or secret access.

Owner risk posture for this registration (#3554, accepted by the owner on
2026-10-07, not asserted as a passing review by this file):

```text
DATA_HANDLING_REVIEW=RISK_ACCEPTED_BY_OWNER   (free/default tier is
    training-eligible unless opted out; opt-out mechanism unconfirmed; shared
    single-key multi-user commercial use not expressly permitted by terms)
COST_STATUS=UNCONFIRMED_ACCEPTED_BY_OWNER     (no cost field is returned; a
    "free" claim is not made anywhere in this contract)
TEXT_AUTO_FALLBACK=OFF
```

Business 14 provider registrations may retain historical/manual route metadata,
but none becomes a Padiem product primary or silent fallback through this file
except the explicit text selection above.
"""

from __future__ import annotations

TEXT_PRIMARY_DECISION = "Owner successor selection 2026-10-07 (#3554): Agnes 3.0 Flash, text role only"
TEXT_PRIMARY_PROVIDER_ID = "agnes-ai"
TEXT_PRIMARY_MODEL_ID = "agnes-ai/agnes-3.0-flash"
TEXT_PRIMARY_UPSTREAM_MODEL = "agnes-3.0-flash"

VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"
VISION_PRIMARY_PROVIDER_ID = None
VISION_PRIMARY_MODEL_ID = None
VISION_PRIMARY_UPSTREAM_MODEL = None

TEXT_SECONDARY_MODEL_ID = None
TEXT_FALLBACK_ENABLED = False

VISION_FALLBACK_MODEL_ID = None
VISION_FALLBACK_DECISION = "UNDECIDED"

VIDEO_PRIMARY_DECISION = "UNDECIDED"
