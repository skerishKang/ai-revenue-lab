"""#3669 — one racer for the multiprocess last-slot lease test.

Deliberately not named ``test_*`` so test discovery does not collect it. It is a
real second process: it opens the same canonical lease store and attempts the
same PHASE B ``consume_action`` on the lease's last durable slot, printing a
single bounded JSON outcome on stdout:

    {"outcome": "ok", "consumed_actions": 1}
    {"outcome": "action_budget_exhausted"}

No browser, no view and no authority material exist here: the loser must never
reach a slot write at all.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from kagent.browser_control_lease_store import (
    BrowserControlLeaseRefusal,
    BrowserControlLeaseStore,
)


def main(argv: list[str]) -> int:
    (
        store_path,
        fingerprint,
        session_ref,
        run_ref,
        workspace_ref,
        owner_ref,
        action,
        observed_origin,
        now_iso,
    ) = argv[1:10]
    moment = datetime.fromisoformat(now_iso).astimezone(timezone.utc)

    with BrowserControlLeaseStore(store_path) as store:
        try:
            projection = store.consume_action(
                fingerprint,
                browser_session_ref=session_ref,
                run_ref=run_ref,
                workspace_ref=workspace_ref,
                owner_ref=owner_ref,
                action=action,
                observed_origin=observed_origin,
                now=moment,
            )
        except BrowserControlLeaseRefusal as exc:
            print(json.dumps({"outcome": exc.code}))
            return 0
        print(json.dumps({"outcome": "ok", "consumed_actions": projection.consumed_actions}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
