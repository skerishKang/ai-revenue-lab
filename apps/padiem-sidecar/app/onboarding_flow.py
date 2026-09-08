"""B53 onboarding state machine / flow.

Deterministic bounded states for:
    register -> configure brand/context -> preview/local health -> ready-for-external-activation

Local ``READY_FOR_EXTERNAL_ACTIVATION`` is not Production activation or
entitlement truth.  Invalid/out-of-order transitions fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from padiem_embedded_runtime.errors import SidecarContractError

REGISTER = "register"
CONFIGURE = "configure"
PREVIEW = "preview"
READY_FOR_EXTERNAL_ACTIVATION = "ready_for_external_activation"
COMPLETED = "completed"

_ONBOARDING_STATES = frozenset({
    REGISTER,
    CONFIGURE,
    PREVIEW,
    READY_FOR_EXTERNAL_ACTIVATION,
    COMPLETED,
})

_TRANSITIONS = {
    (REGISTER, "configure"): CONFIGURE,
    (CONFIGURE, "preview"): PREVIEW,
    (PREVIEW, "activate"): READY_FOR_EXTERNAL_ACTIVATION,
    (READY_FOR_EXTERNAL_ACTIVATION, "complete"): COMPLETED,
}


@dataclass(frozen=True)
class OnboardingState:
    """Immutable onboarding state projection."""

    state: str
    site_name: str
    brand: str
    theme: str
    locale: str
    adapter_id: str
    environment: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "site_name": self.site_name,
            "brand": self.brand,
            "theme": self.theme,
            "locale": self.locale,
            "adapter_id": self.adapter_id,
            "environment": self.environment,
        }


class OnboardingFlow:
    """Deterministic onboarding state machine for B53 product-side conformance.

    No canonical tenant/account truth is created.  The ``ready`` state is
    local-only and is not Production activation.
    """

    def __init__(
        self,
        site_name: str,
        brand: str,
        theme: str,
        locale: str,
        adapter_id: str,
        environment: str,
    ) -> None:
        if not isinstance(site_name, str) or not site_name:
            raise SidecarContractError("site_name must be non-empty text")
        if not isinstance(brand, str) or not brand:
            raise SidecarContractError("brand must be non-empty text")
        if not isinstance(theme, str) or not theme:
            raise SidecarContractError("theme must be non-empty text")
        if locale not in ("ko", "en"):
            raise SidecarContractError("locale must be ko or en")
        if not isinstance(adapter_id, str) or not adapter_id:
            raise SidecarContractError("adapter_id must be non-empty text")
        if environment not in ("dev", "preview", "production"):
            raise SidecarContractError("environment must be dev, preview, or production")
        self._site_name = site_name
        self._brand = brand
        self._theme = theme
        self._locale = locale
        self._adapter_id = adapter_id
        self._environment = environment
        self._state = REGISTER

    @property
    def state(self) -> str:
        return self._state

    def configure(self, brand: str | None = None, theme: str | None = None) -> OnboardingState:
        """Transition register -> configure."""
        if self._state != REGISTER:
            raise SidecarContractError(
                f"invalid onboarding transition: {self._state!r} + configure"
            )
        if brand is not None:
            if not isinstance(brand, str) or not brand:
                raise SidecarContractError("brand must be non-empty text")
            self._brand = brand
        if theme is not None:
            if not isinstance(theme, str) or not theme:
                raise SidecarContractError("theme must be non-empty text")
            self._theme = theme
        self._state = CONFIGURE
        return self._snapshot()

    def preview(self) -> OnboardingState:
        """Transition configure -> preview."""
        if self._state != CONFIGURE:
            raise SidecarContractError(
                f"invalid onboarding transition: {self._state!r} + preview"
            )
        self._state = PREVIEW
        return self._snapshot()

    def activate(self) -> OnboardingState:
        """Transition preview -> ready_for_external_activation.

        Local ready state only; not Production activation or entitlement truth.
        """
        if self._state != PREVIEW:
            raise SidecarContractError(
                f"invalid onboarding transition: {self._state!r} + activate"
            )
        self._state = READY_FOR_EXTERNAL_ACTIVATION
        return self._snapshot()

    def complete(self) -> OnboardingState:
        """Transition ready_for_external_activation -> completed."""
        if self._state != READY_FOR_EXTERNAL_ACTIVATION:
            raise SidecarContractError(
                f"invalid onboarding transition: {self._state!r} + complete"
            )
        self._state = COMPLETED
        return self._snapshot()

    def _snapshot(self) -> OnboardingState:
        return OnboardingState(
            state=self._state,
            site_name=self._site_name,
            brand=self._brand,
            theme=self._theme,
            locale=self._locale,
            adapter_id=self._adapter_id,
            environment=self._environment,
        )