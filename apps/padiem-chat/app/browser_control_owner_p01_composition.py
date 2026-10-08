"""#3782 opt-in trusted B54 human-browser-P01 owner composition (SOURCE ONLY).

No default/product route registration, Worker env discovery, D1 migration or
approval issuance. The canonical P01 engine client and separate current D1
owner are injected by a future independently approved Worker composition.
The app factory only mounts all three routes after an exact closed bundle
passes structural and ownership checks. The route itself ALWAYS revalidates
the signed-in canonical B54 USER session and current independent owner D1.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import PadiemAiEngineClient
from starlette.routing import Route

from .browser_control_owner_p01_decision import browser_control_owner_p01_decision
from .browser_control_owner_p01_finalize import (
    BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
    browser_control_owner_p01_finalize,
)
from .browser_control_owner_p01_tickets import D1BrowserControlOwnerTicketLoader
from .browser_control_owner_ticket_request import (
    BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
    browser_control_owner_ticket_request,
)

BROWSER_CONTROL_OWNER_P01_PRODUCT_COMPOSITION_WIRED = False
BROWSER_CONTROL_OWNER_P01_DECISION_PATH = (
    "/api/claw/browser-control/approvals/decision"
)


@dataclass(frozen=True, slots=True)
class BrowserControlOwnerP01Composition:
    """Closed server-only group, never accepted from a request or model.

    An object with the right Python type is not itself authentication:
    product commissioning must additionally verify physical D1 binding IDs,
    independently signed-in owner, Engine caller credentials, schema and
    canonical live Engine admission. This bundle is not present in Worker.
    """

    owner_d1: Any
    engine_continuation_d1: Any
    ticket_loader: D1BrowserControlOwnerTicketLoader
    engine_client: PadiemAiEngineClient

    def assert_installable(
        self, *, chat_d1: Any, identity_authority: Any, identity_shadow: Any,
    ) -> None:
        if type(self) is not BrowserControlOwnerP01Composition:
            raise TypeError("canonical source-only owner P01 composition required")
        if (
            self.owner_d1 is None
            or self.engine_continuation_d1 is None
            or self.owner_d1 is self.engine_continuation_d1
            or (chat_d1 is not None and chat_d1 is self.owner_d1)
            or not callable(getattr(self.owner_d1, "prepare", None))
            or not callable(getattr(self.engine_continuation_d1, "prepare", None))
            or type(self.ticket_loader) is not D1BrowserControlOwnerTicketLoader
            or self.ticket_loader._owner is not self.owner_d1
            or type(self.engine_client) is not PadiemAiEngineClient
            or self.engine_client.app_id != P01_APP_ID
            or identity_authority is None
            or not callable(getattr(identity_authority, "resolve_auth_session", None))
            or identity_shadow is None
            or not callable(getattr(identity_shadow, "load_projection", None))
        ):
            raise ValueError(
                "independent owner D1, canonical current B54 identity, "
                "and authenticated original Engine caller required"
            )


def routes_for_owner_p01_composition() -> tuple[Route, ...]:
    """Existing handlers only; no second approval authority or new endpoint."""
    return (
        Route(
            BROWSER_CONTROL_OWNER_TICKET_REQUEST_PATH,
            browser_control_owner_ticket_request,
            methods=["POST"],
        ),
        Route(
            BROWSER_CONTROL_OWNER_P01_DECISION_PATH,
            browser_control_owner_p01_decision,
            methods=["POST"],
        ),
        Route(
            BROWSER_CONTROL_OWNER_P01_FINALIZE_PATH,
            browser_control_owner_p01_finalize,
            methods=["POST"],
        ),
    )
