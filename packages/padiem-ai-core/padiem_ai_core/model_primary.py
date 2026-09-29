"""Canonical platform model-primary declaration (#3209).

Product-neutral single source that names Space Bunny Alpha as both the
canonical text primary and the canonical vision primary.

Owner policy encoded here (2026-09-29, Refs #3209, decision source #3143):

```text
TEXT_PRIMARY=Space Bunny Alpha
VISION_PRIMARY=Space Bunny Alpha

TEXT_SECONDARY=NONE
TEXT_FALLBACK=NONE

VISION_FALLBACK=UNDECIDED

VIDEO_ACTIVATION=0
```

Scope locks:

```text
NETWORK_IO=0
RUNTIME_EXECUTION=0
SECRET_ACCESS=0
```

This module performs no I/O, imports nothing outside the standard library,
and carries identifier constants only. The Business 14 catalog
(``apps/korean-ai-platform/app/pilot/kilo_provider.py``) remains the final
execution authority: a declared route can only run if B14 has it registered
and not retired. Parity between the two authorities is asserted by source
tests. The A9/A12 production smokes import ``TEXT_PRIMARY_MODEL_ID`` from
here so their pinned model can never drift by copy-paste.

SenseNova is not part of the active primary/secondary routing policy. Its
provider registration and provider-specific tests remain intact elsewhere;
nothing in this module assigns it a product route.
"""

from __future__ import annotations

TEXT_PRIMARY_PROVIDER_ID = "kilo"
TEXT_PRIMARY_MODEL_ID = "kilo/stealth-space-bunny-alpha"
TEXT_PRIMARY_UPSTREAM_MODEL = "stealth/space-bunny-alpha"

VISION_PRIMARY_PROVIDER_ID = "kilo"
VISION_PRIMARY_MODEL_ID = "kilo/stealth-space-bunny-alpha"
VISION_PRIMARY_UPSTREAM_MODEL = "stealth/space-bunny-alpha"

TEXT_SECONDARY_MODEL_ID = None
TEXT_FALLBACK_ENABLED = False

VISION_FALLBACK_MODEL_ID = None
VISION_FALLBACK_DECISION = "UNDECIDED"

VIDEO_PRIMARY_DECISION = "UNDECIDED"
