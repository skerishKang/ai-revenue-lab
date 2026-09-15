"""B53 Padiem Sidecar product adapter — consumes IP-SIDECAR primitives only.

B53 owns commercial/product adapter semantics. Generic reusable runtime
primitives stay under IP-SIDECAR; this adapter never copies or reimplements
them. Engine and Control Plane remain fake/stub ports for this slice.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from padiem_embedded_runtime.bootstrap import BootstrapConfig
from padiem_embedded_runtime.bridge import BridgeOutcome, intake_host_payload
from padiem_embedded_runtime.diagnostics import IntegrationDiagnostics
from padiem_embedded_runtime.engine_port import DeterministicFakeEnginePort, EnginePort
from padiem_embedded_runtime.errors import SidecarContractError
from padiem_embedded_runtime.lifecycle import EmbeddedShell, HostSafeResult
from padiem_embedded_runtime.streaming_lifecycle import (
    PublicErrorPresentation,
    RetryAffordancePresentation,
    StreamFeedGuard,
    StreamLifecyclePresentation,
    present_public_error,
    present_retry_affordance,
    present_stream_lifecycle,
)
from padiem_embedded_runtime.evidence import (
    CitationPresentation,
    present_citations,
)
from padiem_embedded_runtime.attachment_input import (
    AttachmentRefPresentation,
    SelectionPresentation,
    UploadLifecyclePresentation,
    present_attachment_ref,
    present_selections,
    present_upload_lifecycle,
)
from padiem_embedded_runtime.approval_presentation import (
    ApprovalStatePresentation,
    ConfirmationIntentPresentation,
    ProposalPresentation,
    PublicReferenceDisplay,
    present_approval_proposals,
    present_approval_state,
    present_confirmation_intent,
    present_public_reference,
)

B53_PRODUCT_ID = "padiem-sidecar"
B53_PRODUCT_NAME = "Padiem Sidecar"
ALLOWED_INSTALL_MODES = frozenset({"embed", "snippet", "panel"})
MAX_THEME_CHARS = 32
MAX_BRAND_CHARS = 64


class SidecarProductConfig:
    """B53-owned product configuration envelope with bounded metadata only."""

    def __init__(
        self,
        product_id: str,
        product_name: str,
        install_mode: str,
        theme: str,
        brand: str,
        locale: str = "ko",
    ) -> None:
        if not isinstance(product_id, str) or product_id != B53_PRODUCT_ID:
            raise SidecarContractError("product_id must be the bounded B53 id")
        if not isinstance(product_name, str) or len(product_name) > MAX_BRAND_CHARS:
            raise SidecarContractError("product_name exceeds the bound")
        if install_mode not in ALLOWED_INSTALL_MODES:
            raise SidecarContractError("install_mode is not allowlisted")
        if not isinstance(theme, str) or len(theme) > MAX_THEME_CHARS:
            raise SidecarContractError("theme exceeds the bound")
        if not isinstance(brand, str) or len(brand) > MAX_BRAND_CHARS:
            raise SidecarContractError("brand exceeds the bound")
        if locale not in ("ko", "en"):
            raise SidecarContractError("locale must be ko or en")
        self.product_id = product_id
        self.product_name = product_name
        self.install_mode = install_mode
        self.theme = theme
        self.brand = brand
        self.locale = locale

    def to_public_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "product_name": self.product_name,
            "install_mode": self.install_mode,
            "theme": self.theme,
            "brand": self.brand,
            "locale": self.locale,
        }


class StubControlPlaneContextPort:
    """B53-owned handoff-only Control Plane context port (conformance stub).

    Returns bounded static product context for the local journey. It performs
    no network, Service Binding, credential read, tenant minting, or
    authority decision; real Control Plane authority stays outside B53.
    """

    MAX_CONTEXT_KEYS = 8
    MAX_KEY_CHARS = 64
    MAX_VALUE_CHARS = 512

    def __init__(self, context: Mapping[str, object] | None = None) -> None:
        raw = context if isinstance(context, Mapping) else {}
        if len(raw) > self.MAX_CONTEXT_KEYS:
            raise SidecarContractError("stub context exceeds the key bound")
        self._context: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise SidecarContractError("stub context entries must be text pairs")
            if len(key) > self.MAX_KEY_CHARS or len(value) > self.MAX_VALUE_CHARS:
                raise SidecarContractError("stub context entry exceeds the bound")
            self._context[key] = value

    def product_context(self) -> dict[str, object]:
        return {
            "status": "stub",
            "context": dict(self._context),
            "tenant_authority": False,
            "transport": False,
        }


class ProductAdapter:
    """B53-owned adapter that translates trusted/fake host input into IP-SIDECAR primitives.

    All validation/state authority stays in IP-SIDECAR; this adapter only
    delegates and carries bounded product-facing metadata.
    """

    def __init__(
        self,
        config: SidecarProductConfig,
        engine_port: EnginePort | None = None,
        control_plane_port: StubControlPlaneContextPort | None = None,
    ) -> None:
        if not isinstance(config, SidecarProductConfig):
            raise SidecarContractError("adapter requires a SidecarProductConfig")
        if engine_port is not None and not isinstance(engine_port, EnginePort):
            raise SidecarContractError("engine_port must implement the canonical EnginePort contract")
        self._config = config
        self._engine = engine_port if engine_port is not None else DeterministicFakeEnginePort({})
        if control_plane_port is not None and not isinstance(
            control_plane_port, StubControlPlaneContextPort
        ):
            raise SidecarContractError("control_plane_port must be the B53 stub context port")
        self._control_plane = (
            control_plane_port
            if control_plane_port is not None
            else StubControlPlaneContextPort()
        )
        self._shell = EmbeddedShell(
            BootstrapConfig(host_id="b53-host", shell_version="1.0.0", locale=config.locale)
        )
        self._diagnostics: IntegrationDiagnostics | None = None

    def intake(
        self,
        bootstrap_raw: Mapping[str, object],
        context_raw: Mapping[str, object],
    ) -> BridgeOutcome:
        outcome = intake_host_payload(bootstrap_raw, context_raw, self._shell)
        self._diagnostics = outcome.diagnostics
        return outcome

    def disable(self, reason: str = "") -> HostSafeResult:
        return self._shell.disable(reason)

    def stream_event(self, raw: Mapping[str, object]) -> StreamLifecyclePresentation:
        return present_stream_lifecycle(raw)

    def stream_feed(self, events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        guard = StreamFeedGuard()
        feed: list[dict[str, object]] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            presentation = present_stream_lifecycle(event)
            projected, ordering = guard.observe(presentation)
            feed.append({"ordering": ordering, **projected.to_public_dict()})
        return feed

    def public_error(self, raw: Mapping[str, object]) -> PublicErrorPresentation:
        return present_public_error(raw)

    def retry_affordance(self, raw: Mapping[str, object]) -> RetryAffordancePresentation:
        return present_retry_affordance(raw)

    def citations(self, items: Sequence[object]) -> CitationPresentation:
        return present_citations(items)

    def selections(self, items: Sequence[object]) -> SelectionPresentation:
        return present_selections(items)

    def attachment_ref(self, ref: object) -> AttachmentRefPresentation:
        return present_attachment_ref(ref)

    def upload_lifecycle(self, raw: Mapping[str, object]) -> UploadLifecyclePresentation:
        return present_upload_lifecycle(raw)

    def approval_proposals(self, items: Sequence[object]) -> ProposalPresentation:
        return present_approval_proposals(items)

    def approval_state(self, raw: Mapping[str, object]) -> ApprovalStatePresentation:
        return present_approval_state(raw)

    def confirmation_intent(self, raw: Mapping[str, object]) -> ConfirmationIntentPresentation:
        return present_confirmation_intent(raw)

    def public_reference(self, ref: str) -> PublicReferenceDisplay:
        return present_public_reference(ref)

    @property
    def config(self) -> SidecarProductConfig:
        return self._config

    @property
    def shell(self) -> EmbeddedShell:
        return self._shell

    @property
    def diagnostics(self) -> IntegrationDiagnostics | None:
        return self._diagnostics

    @property
    def engine_port(self) -> EnginePort:
        return self._engine

    @property
    def control_plane_port(self) -> StubControlPlaneContextPort:
        return self._control_plane

    def control_plane_context(self) -> dict[str, object]:
        return self._control_plane.product_context()
