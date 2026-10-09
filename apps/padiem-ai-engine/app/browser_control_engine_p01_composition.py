"""#3782 one-source, source-only Engine browser P01 service composition.

Reuse existing Engine D1 continuations/receipts, independently owned human-P01
D1 and current authenticated Control Plane USER session. No Worker factory
calls this; no new D1, routes, credentials, browser inputs or model calls.
One closed set of services avoids independently mismatched original-run owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.browser_control_broker_original_read import (
    AuthenticatedEngineBrowserOriginalRead,
)
from app.browser_control_broker_receipt_read import (
    AuthenticatedBrowserP01ReceiptReadEngineService,
)
from app.browser_control_first_party_session_authority import (
    FirstPartyControlPlaneBrowserP01SessionAuthority,
)
from app.browser_control_owner_p01_d1_read import IndependentOwnerP01D1Reader
from app.browser_control_owner_p01_resume import (
    IndependentlyApprovedBrowserControlEngineResume,
)
from app.browser_control_owner_p01_ticket_issuer import (
    AuthenticatedEngineBrowserP01TicketIssuer,
)
from app.browser_control_owner_ticket_issue_service import (
    BrowserControlOwnerTicketIssueEngineService,
)
from app.browser_control_p01_receipt import (
    CloudflareD1BrowserControlP01ReceiptStore,
)
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.tool_execution_service import ToolExecutionEngineService

BROWSER_CONTROL_ENGINE_P01_PRODUCT_COMPOSITION_WIRED = False


@dataclass(frozen=True, slots=True)
class SourceOnlyOriginalBrowserP01EngineServices:
    ticket_issue: BrowserControlOwnerTicketIssueEngineService
    owner_resume: IndependentlyApprovedBrowserControlEngineResume
    broker_receipt_read: AuthenticatedBrowserP01ReceiptReadEngineService
    broker_original_read: AuthenticatedEngineBrowserOriginalRead

    def named_engine_service_fields(self) -> dict[str, Any]:
        """Exact existing EngineServices fields; no Worker registration."""
        return {
            "browser_p01_ticket_issue": self.ticket_issue,
            "browser_p01_owner_resume": self.owner_resume,
            "browser_p01_broker_receipt_read": self.broker_receipt_read,
            "browser_p01_broker_original_read": self.broker_original_read,
        }


def compose_source_only_original_browser_p01_services(
    *,
    tool_service: ToolExecutionEngineService,
    continuation_store: CloudflareD1IdentityBoundContinuationStore,
    receipt_store: CloudflareD1BrowserControlP01ReceiptStore,
    owner_d1: Any,
    current_session_authority: FirstPartyControlPlaneBrowserP01SessionAuthority,
) -> SourceOnlyOriginalBrowserP01EngineServices:
    """Reject split Engine/Owner P01 authority, including valid-looking stubs.

    Only services that already rely on ONE original Engine store, ONE receipt
    store and a separate human-approval D1 are co-composed. The current CP
    session authority must be the existing first-party implementation, not
    a caller-provided static `CurrentCanonicalHumanSession` or arbitrary
    callback. Real Worker activation requires independent owner binding and
    security review; caller of this function alone cannot enable a route.
    """
    if (
        type(tool_service) is not ToolExecutionEngineService
        or type(continuation_store) is not CloudflareD1IdentityBoundContinuationStore
        or type(receipt_store) is not CloudflareD1BrowserControlP01ReceiptStore
        or type(current_session_authority)
        is not FirstPartyControlPlaneBrowserP01SessionAuthority
        or not callable(getattr(current_session_authority._shadow, "load_projection", None))
        or not callable(getattr(current_session_authority._client, "resolve_auth_session", None))
        or tool_service._continuation_store is not continuation_store
        or tool_service._browser_control_p01_receipts is not receipt_store
        or receipt_store._binding is not continuation_store._binding
        or owner_d1 is None
        or owner_d1 is continuation_store._binding
        or not callable(getattr(owner_d1, "prepare", None))
    ):
        raise ValueError("one canonical Engine D1, separate Owner D1 and live CP USER required")

    human_reader = tool_service._browser_control_human_p01_resolver
    if (
        type(human_reader) is not IndependentOwnerP01D1Reader
        or human_reader._owner is not owner_d1
    ):
        raise ValueError("Tool Engine has no exact independently approved Owner D1 reader")

    issuer = AuthenticatedEngineBrowserP01TicketIssuer(
        engine_store=continuation_store, owner_binding=owner_d1,
        session_authority=current_session_authority,
    )
    result = SourceOnlyOriginalBrowserP01EngineServices(
        ticket_issue=BrowserControlOwnerTicketIssueEngineService(issuer=issuer),
        owner_resume=IndependentlyApprovedBrowserControlEngineResume(
            engine_service=tool_service, engine_store=continuation_store,
            owner_reader=human_reader,
        ),
        broker_receipt_read=AuthenticatedBrowserP01ReceiptReadEngineService(
            receipts=receipt_store,
        ),
        broker_original_read=AuthenticatedEngineBrowserOriginalRead(
            engine_store=continuation_store, receipts=receipt_store,
        ),
    )
    return result
