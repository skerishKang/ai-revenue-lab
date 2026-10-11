"""#3611 — one racer for the multi-process durable one-shot test.

Deliberately not named ``test_*`` so test discovery does not collect it. It is a
real second process: it opens the same SQLite file, authorizes the same open and
then attempts the same atomic ``ADMITTED -> EXECUTING`` redemption, printing a
single bounded JSON outcome on stdout.

    {"outcome": "ok"}
    {"outcome": "command_already_started"}

No browser is started and no view is created here: the loser must never reach a
host at all.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

from kagent.browser_open import (
    BROWSER_OPEN_TOOL_ID,
    BrowserOpenRefusal,
    BrowserOpenRequest,
    browser_open_fingerprint,
    browser_open_target_ref,
)
from kagent.browser_open_authority import (
    BrowserOpenAuthorityEvidence,
    DeterministicBrowserOpenAuthorityEvidencePort,
    P01LocalPermissionBrowserOpenAuthorizationPort,
)
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_durable_run import DurableRunRecord
from kagent.local_agent_durable_run_store import DurableRunStore
from kagent.local_agent_permissions import LocalPermissionRequest, default_device_permission_profile

SAFE_URL = "https://example.com/report?id=7#section"


def main(argv: list[str]) -> int:
    store_path, command_id, run_id, now_iso = argv[1], argv[2], argv[3], argv[4]
    moment = datetime.fromisoformat(now_iso).astimezone(timezone.utc)

    device = LocalAgentDeviceProfile(
        device_id="device_3611",
        workspace_ref="workspace_3611",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root_work", windows_path=r"E:\work"),),
    )
    request = BrowserOpenRequest(
        open_id="open_1",
        run_id=run_id,
        device_id="device_3611",
        ticket_ref="ticket_3611",
        target_url=SAFE_URL,
        requested_at=moment,
        ttl_seconds=300,
    )
    fingerprint = browser_open_fingerprint(request)
    pause = ApprovalPause(
        pause_id="pause_3611",
        run_id=run_id,
        agent_runtime_id="runtime_3611",
        tool_id=BROWSER_OPEN_TOOL_ID,
        invocation_sha256=fingerprint,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=moment - timedelta(seconds=5),
        expires_at=moment + timedelta(seconds=600),
        approval_scope=(BROWSER_OPEN_TOOL_ID,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="decision_3611",
        pause_id="pause_3611",
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="p01_authority.3611",
        evidence_ref="evidence.p01.3611",
        decided_at=moment - timedelta(seconds=4),
    )
    evidence = BrowserOpenAuthorityEvidence(
        evidence_ref="evidence.p01.3611",
        request_fingerprint=fingerprint,
        command_id=command_id,
        permission_request=LocalPermissionRequest(
            action_id="browser_open_open_1",
            run_id=run_id,
            device_id="device_3611",
            capability=request.capability,
            target_ref=browser_open_target_ref(request),
        ),
        approval_pause=pause,
        approval_decision=decision,
        local_policy_ref="local:require_p01_approval",
        admission_ref="admission.3611",
        revision_ref="revision.7f3c1a9e",
        expires_at=moment + timedelta(seconds=600),
    )

    with DurableRunStore(store_path) as store:
        record = store.get(command_id=command_id)
        if record is None:
            raise SystemExit("the parent must put the admitted record first")
        if not isinstance(record, DurableRunRecord):  # pragma: no cover - defensive
            raise SystemExit("durable record is invalid")
        port = P01LocalPermissionBrowserOpenAuthorizationPort(
            device=device,
            permission_profile=default_device_permission_profile(device=device),
            store=store,
            evidence_port=DeterministicBrowserOpenAuthorityEvidencePort((evidence,)),
        )
        try:
            grant, _ = port.authorize(request=request, now=moment)
        except BrowserOpenRefusal as exc:
            print(json.dumps({"outcome": exc.code}))
            return 0
        try:
            port.redeem(
                redemption_ref=command_id,
                request_fingerprint=grant.request_fingerprint,
                open_id=grant.open_id,
                run_ref=grant.run_id,
                now=moment,
            )
        except BrowserOpenRefusal as exc:
            print(json.dumps({"outcome": exc.code}))
            return 0
    print(json.dumps({"outcome": "ok"}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
