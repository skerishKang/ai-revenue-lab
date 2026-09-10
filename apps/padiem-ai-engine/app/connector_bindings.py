"""Engine Gmail trusted binding entry + composition seam (WO-10 PR-B).

The Engine performs only:

* one server-side assembly of a Core ``EngineToolBinding`` per (app_id, grant)
  pair — never from caller JSON, never inferred at request time;
* one cached resolver factory that the canonical composition root injects
  into ``ToolExecutionEngineService`` and
  ``CanonicalIdempotencyOrchestrationEngineService``;
* fail-closed posture: when no production Gmail port or grant store is bound
  yet (``GMAIL_PORT_BOUND_IN_PRODUCTION is False``) the resolver returns
  ``None`` for every app, so ``tool_runtime_unavailable`` (503) continues to
  answer every request exactly as the WO-1 source seam did.

Path scope: ``apps/padiem-ai-engine/**``. No manifest flips, no wrangler
changes, no real OAuth/HTTP wiring, no Core/Claw changes, no new
dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from padiem_ai_core import (
    AgentExecutionBudget,
    BoundedAgentDefinition,
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_CONNECTOR_ID,
    GmailReadPort,
    ToolAuthorizationContext,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntime,
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
    gmail_read_tool_specs,
)
from padiem_ai_core.drive_capability import (
    DRIVE_CANONICAL_TOOL_IDS,
    DRIVE_CONNECTOR_ID,
    DriveCapability,
    DriveCapabilityGrant,
    DriveContractError,
    DriveReadPort,
    drive_read_tool_specs,
    register_drive_read_tools,
)
from padiem_ai_core.telegram_capability import (
    TELEGRAM_CANONICAL_TOOL_IDS,
    TELEGRAM_CONNECTOR_ID,
    TelegramCapability,
    TelegramCapabilityGrant,
    TelegramContractError,
    TelegramReadPort,
    register_telegram_read_tools,
    telegram_read_tool_specs,
)
from padiem_ai_core.tool_runtime import (
    ToolRuntime as _CoreToolRuntime,  # identity-gate check below
)
from padiem_ai_core.tool_registry import RegisteredTool

from app.tool_projection import (
    EngineToolBinding,
    EngineToolProjectionError,
    TrustedToolAuthority,
)

# Server-side identifiers (deployment decision D28, pre-activation). They
# identify the trusted Engine composition slot for the Gmail read connector
# before the OAuth credential store is bound.
GMAIL_REFERENCE_APP_ID = "b54-padiem-claw"
GMAIL_MAIL_READER_AGENT_ID = "agent:padiem:claw_mail_reader@1"

DRIVE_REFERENCE_APP_ID = "b54-padiem-claw-drive"
DRIVE_AGENT_ID = "agent:padiem:claw_drive_reader@1"

# Server-side identifiers for the promoted Telegram read connector (#2353).
# The slot is pre-activation: the resolver stays None until a bot-token port
# and server-derived grants are both composed by the canonical root.
TELEGRAM_REFERENCE_APP_ID = "b54-padiem-claw-telegram"
TELEGRAM_AGENT_ID = "agent:padiem:claw_telegram_reader@1"

# Server-side identifiers (deployment decision D28, pre-activation). They
# identify the trusted Engine composition slot for the Gmail read connector
# before the OAuth credential store is bound.


@dataclass(frozen=True, slots=True)
class GmailGrant:
    """Server-resolved grant fact for one canonical Agent. Never derived from
    caller JSON — caller fields like ``granted_auth_scopes`` and
    ``authorization`` are explicitly rejected at the Engine edge.

    ``granted_scopes`` carries the bounded Core auth_scope token set (e.g.
    ``("gmail.readonly",)``). The exact provider OAuth URL is forwarded to
    the trusted port as ``required_scopes`` by the Core connector itself.
    """

    app_id: str
    canonical_agent_id: str
    binding_ref: str
    actor_ref: str
    granted_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DriveGrant:
    """Server-resolved grant fact for one canonical Drive Agent.

    ``granted_capabilities`` carries only explicit DriveCapability values
    resolved server-side from grant references; never derived from caller
    JSON. Raw OAuth/access/refresh tokens can never appear here.
    """

    app_id: str
    canonical_agent_id: str
    binding_ref: str
    actor_ref: str
    granted_capabilities: tuple[DriveCapability, ...]

    def __post_init__(self) -> None:
        # Fail-closed parity with Core's DriveCapabilityGrant: a grant that
        # repeats a capability is ambiguous and must never reach binding.
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, DriveCapability) for item in self.granted_capabilities
        ):
            raise DriveContractError(
                "granted_capabilities must contain DriveCapability values"
            )
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise DriveContractError("granted_capabilities must be unique")


@dataclass(frozen=True, slots=True)
class TelegramGrant:
    """Server-resolved grant fact for one canonical Telegram Agent (#2353).

    ``granted_capabilities`` carries only explicit TelegramCapability values
    resolved server-side from grant references; never derived from caller
    JSON. The raw bot token can never appear here.
    """

    app_id: str
    canonical_agent_id: str
    binding_ref: str
    actor_ref: str
    granted_capabilities: tuple[TelegramCapability, ...]

    def __post_init__(self) -> None:
        # Fail-closed parity with Core's TelegramCapabilityGrant: a grant that
        # repeats a capability is ambiguous and must never reach binding.
        if not isinstance(self.granted_capabilities, tuple) or any(
            not isinstance(item, TelegramCapability) for item in self.granted_capabilities
        ):
            raise TelegramContractError(
                "granted_capabilities must contain TelegramCapability values"
            )
        if len(self.granted_capabilities) != len(set(self.granted_capabilities)):
            raise TelegramContractError("granted_capabilities must be unique")
        if any(
            capability is not TelegramCapability.READ for capability in self.granted_capabilities
        ):
            raise TelegramContractError(
                "only the READ capability may be granted to a Telegram binding"
            )


def _gmail_definition(*, app_id: str, canonical_agent_id: str) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id=canonical_agent_id,
        publisher_id="padiem",
        title="Claw mail reader",
        description="Read-only Gmail projection for Padiem Claw",
        instruction=(
            "Read selected mail through the trusted Gmail port; never send "
            "or modify."
        ),
        output_contract_ref="output:text@1",
        allowed_tool_ids=GMAIL_CANONICAL_TOOL_IDS,
        execution_budget=AgentExecutionBudget(),
    )


def _gmail_policy() -> TrustedAgentRuntimePolicy:
    specs = {spec.id: spec for spec in gmail_read_tool_specs()}
    return TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1024,
        max_steps_cap=8,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=tuple(
            ToolRuntimeBinding(
                canonical_tool_id=canonical,
                runtime_tool_id=spec_id,
            )
            for canonical, spec_id in zip(
                GMAIL_CANONICAL_TOOL_IDS,
                (
                    "gmail.search_messages",
                    "gmail.get_message",
                    "gmail.get_thread",
                ),
            )
            for _ in (specs.get(spec_id),)  # static-only check below
            if spec_id in specs
        ),
    )


def _drive_definition(*, app_id: str, canonical_agent_id: str) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id=canonical_agent_id,
        publisher_id="padiem",
        title="Claw drive reader",
        description="Read-only Google Drive projection for Padiem Claw",
        instruction=(
            "Read selected Drive resources through the trusted Drive port; "
            "never write or modify."
        ),
        output_contract_ref="output:text@1",
        allowed_tool_ids=DRIVE_CANONICAL_TOOL_IDS,
        execution_budget=AgentExecutionBudget(),
    )


def _drive_policy() -> TrustedAgentRuntimePolicy:
    specs = {spec.id: spec for spec in drive_read_tool_specs()}
    return TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1024,
        max_steps_cap=8,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=tuple(
            ToolRuntimeBinding(
                canonical_tool_id=canonical,
                runtime_tool_id=spec_id,
            )
            for canonical, spec_id in zip(
                DRIVE_CANONICAL_TOOL_IDS,
                (
                    "drive.search_files",
                    "drive.list_recent_files",
                    "drive.get_file_metadata",
                    "drive.read_file_content",
                ),
            )
            for _ in (specs.get(spec_id),)
            if spec_id in specs
        ),
    )


def _telegram_definition(*, app_id: str, canonical_agent_id: str) -> BoundedAgentDefinition:
    return BoundedAgentDefinition(
        agent_id=canonical_agent_id,
        publisher_id="padiem",
        title="Claw telegram reader",
        description="Read-only Telegram Bot API projection for Padiem Claw",
        instruction=(
            "Read the bot's own identity and server-paired chat metadata "
            "through the trusted Telegram port; never send or modify."
        ),
        output_contract_ref="output:text@1",
        allowed_tool_ids=TELEGRAM_CANONICAL_TOOL_IDS,
        execution_budget=AgentExecutionBudget(),
    )


def _telegram_policy() -> TrustedAgentRuntimePolicy:
    specs = {spec.id: spec for spec in telegram_read_tool_specs()}
    return TrustedAgentRuntimePolicy(
        context_policy_ref="context:default",
        model_policy_ref="model:auto",
        output_contract_ref="output:text@1",
        task_type="general",
        optimize_for="balanced",
        max_tokens=1024,
        max_steps_cap=8,
        context_policy={},
        model_policy={},
        output_contract={},
        tool_bindings=tuple(
            ToolRuntimeBinding(
                canonical_tool_id=canonical,
                runtime_tool_id=spec_id,
            )
            for canonical, spec_id in zip(
                TELEGRAM_CANONICAL_TOOL_IDS,
                (
                    "telegram.get_bot_info",
                    "telegram.get_chat_info",
                ),
            )
            for _ in (specs.get(spec_id),)
            if spec_id in specs
        ),
    )


def gmail_tool_binding(
    *,
    grant: GmailGrant,
    port: GmailReadPort,
) -> EngineToolBinding:
    """Assemble one server-trusted EngineToolBinding from a server grant.

    The Core connector registration is the existing ``register_gmail_read_tools``
    entry point — Core is the sole tool runtime, the Engine never instantiates
    a second runtime. The Engine never invents a ``ToolAuthorizationContext``
    from request JSON; the grant's ``granted_scopes`` is the only source of
    authority.
    """
    if not isinstance(grant, GmailGrant):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Gmail binding requires a server-resolved GmailGrant.",
            status_code=503,
        )
    if not callable(getattr(port, "get_json", None)):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Gmail binding requires a Core GmailReadPort.",
            status_code=503,
        )
    if grant.app_id != GMAIL_REFERENCE_APP_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Gmail grant app_id does not match the trusted Engine slot.",
            status_code=403,
        )
    if grant.canonical_agent_id != GMAIL_MAIL_READER_AGENT_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Gmail grant canonical_agent_id does not match the bound Agent.",
            status_code=403,
        )

    runtime = ToolRuntime()
    # ``register_gmail_read_tools`` is the existing Core entry point; it
    # registers all three readonly ToolSpecs and binds them to ``port`` with
    # the supplied binding/actor refs.
    from padiem_ai_core.connectors import register_gmail_read_tools  # local import to avoid cycle
    register_gmail_read_tools(
        runtime,
        port,
        binding_ref=grant.binding_ref,
        actor_ref=grant.actor_ref,
    )

    specs = list(gmail_read_tool_specs())
    registry = ToolRegistrySnapshot.from_entries(
        tuple(
            sorted(
                (
                    RegisteredTool.from_spec(
                        canonical_tool_id=canonical,
                        runtime_spec=spec,
                    )
                    for canonical, spec in zip(
                        GMAIL_CANONICAL_TOOL_IDS,
                        specs,
                    )
                ),
                key=lambda entry: entry.canonical_tool_id,
            )
        )
    )

    definition = _gmail_definition(
        app_id=grant.app_id,
        canonical_agent_id=grant.canonical_agent_id,
    )
    policy = _gmail_policy()
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=grant.app_id,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=tuple(grant.granted_scopes),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=grant.canonical_agent_id,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )

    # Identity-gate: refuse any non-Core tool runtime. The EngineToolBinding
    # ``__post_init__`` already enforces this with ``type(...) is ToolRuntime``,
    # but the local reference keeps the invariant readable at this seam.
    assert type(runtime) is _CoreToolRuntime

    return EngineToolBinding(
        app_id=grant.app_id,
        tool_runtime=runtime,
        registry=registry,
        authorities={grant.canonical_agent_id: authority},
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )


def drive_tool_binding(
    *,
    grant: DriveGrant,
    port: DriveReadPort,
) -> EngineToolBinding:
    """Assemble one server-trusted EngineToolBinding from a server Drive grant.

    Core entry point is ``register_drive_read_tools``; the Engine never
    instantiates a second runtime. The Engine never invents a
    ``ToolAuthorizationContext`` from request JSON; the grant's
    ``granted_capabilities`` is the only source of authority.
    """

    if not isinstance(grant, DriveGrant):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Drive binding requires a server-resolved DriveGrant.",
            status_code=503,
        )
    if not callable(getattr(port, "get_json", None)) or not callable(
        getattr(port, "get_text", None)
    ):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Drive binding requires a Core DriveReadPort.",
            status_code=503,
        )
    if grant.app_id != DRIVE_REFERENCE_APP_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Drive grant app_id does not match the trusted Engine slot.",
            status_code=403,
        )
    if grant.canonical_agent_id != DRIVE_AGENT_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Drive grant canonical_agent_id does not match the bound Agent.",
            status_code=403,
        )

    runtime = ToolRuntime()
    register_drive_read_tools(
        runtime,
        port,
        binding_ref=grant.binding_ref,
        actor_ref=grant.actor_ref,
    )

    specs = list(drive_read_tool_specs())
    registry = ToolRegistrySnapshot.from_entries(
        tuple(
            sorted(
                (
                    RegisteredTool.from_spec(
                        canonical_tool_id=canonical,
                        runtime_spec=spec,
                    )
                    for canonical, spec in zip(
                        DRIVE_CANONICAL_TOOL_IDS,
                        specs,
                    )
                ),
                key=lambda entry: entry.canonical_tool_id,
            )
        )
    )

    definition = _drive_definition(
        app_id=grant.app_id,
        canonical_agent_id=grant.canonical_agent_id,
    )
    policy = _drive_policy()
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=grant.app_id,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=tuple(grant.granted_capabilities),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=grant.canonical_agent_id,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )
    assert type(runtime) is _CoreToolRuntime

    return EngineToolBinding(
        app_id=grant.app_id,
        tool_runtime=runtime,
        registry=registry,
        authorities={grant.canonical_agent_id: authority},
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )


def telegram_tool_binding(
    *,
    grant: TelegramGrant,
    port: TelegramReadPort,
) -> EngineToolBinding:
    """Assemble one server-trusted EngineToolBinding from a server Telegram grant.

    Core entry point is ``register_telegram_read_tools``; the Engine never
    instantiates a second runtime. The Engine never invents a
    ``ToolAuthorizationContext`` from request JSON; the grant's
    ``granted_capabilities`` is the only source of authority. The raw bot
    token stays inside the trusted port and never crosses this seam.
    """

    if not isinstance(grant, TelegramGrant):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Telegram binding requires a server-resolved TelegramGrant.",
            status_code=503,
        )
    if not callable(getattr(port, "get_json", None)):
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Telegram binding requires a Core TelegramReadPort.",
            status_code=503,
        )
    if grant.app_id != TELEGRAM_REFERENCE_APP_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Telegram grant app_id does not match the trusted Engine slot.",
            status_code=403,
        )
    if grant.canonical_agent_id != TELEGRAM_AGENT_ID:
        raise EngineToolProjectionError(
            "invalid_tool_binding",
            "Telegram grant canonical_agent_id does not match the bound Agent.",
            status_code=403,
        )

    runtime = ToolRuntime()
    register_telegram_read_tools(
        runtime,
        port,
        binding_ref=grant.binding_ref,
        actor_ref=grant.actor_ref,
    )

    specs = list(telegram_read_tool_specs())
    registry = ToolRegistrySnapshot.from_entries(
        tuple(
            sorted(
                (
                    RegisteredTool.from_spec(
                        canonical_tool_id=canonical,
                        runtime_spec=spec,
                    )
                    for canonical, spec in zip(
                        TELEGRAM_CANONICAL_TOOL_IDS,
                        specs,
                    )
                ),
                key=lambda entry: entry.canonical_tool_id,
            )
        )
    )

    definition = _telegram_definition(
        app_id=grant.app_id,
        canonical_agent_id=grant.canonical_agent_id,
    )
    policy = _telegram_policy()
    compiled = compile_agent_profile(definition, policy)
    authorization = ToolAuthorizationContext(
        app_id=grant.app_id,
        agent_id=compiled.runtime_profile.id,
        granted_auth_scopes=tuple(grant.granted_capabilities),
    )
    authority = TrustedToolAuthority(
        canonical_agent_id=grant.canonical_agent_id,
        definition=definition,
        compiled=compiled,
        authorization=authorization,
    )
    assert type(runtime) is _CoreToolRuntime

    return EngineToolBinding(
        app_id=grant.app_id,
        tool_runtime=runtime,
        registry=registry,
        authorities={grant.canonical_agent_id: authority},
        authorization_provider=None,
        resource_policy=ToolResourcePolicy(),
    )


def build_tool_binding_resolver(
    *,
    gmail_port: GmailReadPort | None,
    grants: Mapping[str, GmailGrant] | None = None,
    grants_loader: Callable[[], Awaitable[Mapping[str, GmailGrant]]] | None = None,
    drive_port: DriveReadPort | None = None,
    drive_grants: Mapping[str, DriveGrant] | None = None,
    drive_grants_loader: Callable[[], Awaitable[Mapping[str, DriveGrant]]] | None = None,
    telegram_port: TelegramReadPort | None = None,
    telegram_grants: Mapping[str, TelegramGrant] | None = None,
    telegram_grants_loader: (
        Callable[[], Awaitable[Mapping[str, TelegramGrant]]] | None
    ) = None,
) -> Callable[[str], EngineToolBinding | None] | None:
    """Build the cached per-app_id resolver the composition root injects.

    Gmail, Drive and Telegram resolvers coexist (#2353): a request is routed
    to the first matching grant type. When either port is ``None`` or its
    grant mapping is empty, that connector's resolver is absent.

    * ``gmail_port is None and drive_port is None and telegram_port is None``
      ⇒ ``None``.
    * ``grants`` / ``drive_grants`` / ``telegram_grants`` are pre-resolved
      mappings; ``*_loader`` async factories are ignored until pre-resolved
      (fail-closed until then).
    """
    gmail_resolver: Callable[[str], EngineToolBinding | None] | None = None
    if gmail_port is not None:
        effective_grants = grants
        if effective_grants is None and grants_loader is not None:
            effective_grants = {}
        if effective_grants:
            cache: dict[str, EngineToolBinding] = {}

            def _gmail_resolver(app_id: str) -> EngineToolBinding | None:
                grant = effective_grants.get(app_id)
                if grant is None:
                    return None
                cached = cache.get(app_id)
                if cached is not None:
                    return cached
                binding = gmail_tool_binding(grant=grant, port=gmail_port)
                cache[app_id] = binding
                return binding

            gmail_resolver = _gmail_resolver

    drive_resolver: Callable[[str], EngineToolBinding | None] | None = None
    if drive_port is not None:
        effective_drive_grants = drive_grants
        if effective_drive_grants is None and drive_grants_loader is not None:
            effective_drive_grants = {}
        if effective_drive_grants:
            cache: dict[str, EngineToolBinding] = {}

            def _drive_resolver(app_id: str) -> EngineToolBinding | None:
                grant = effective_drive_grants.get(app_id)
                if grant is None:
                    return None
                cached = cache.get(app_id)
                if cached is not None:
                    return cached
                binding = drive_tool_binding(grant=grant, port=drive_port)
                cache[app_id] = binding
                return binding

            drive_resolver = _drive_resolver

    telegram_resolver: Callable[[str], EngineToolBinding | None] | None = None
    if telegram_port is not None:
        effective_telegram_grants = telegram_grants
        if effective_telegram_grants is None and telegram_grants_loader is not None:
            effective_telegram_grants = {}
        if effective_telegram_grants:
            cache: dict[str, EngineToolBinding] = {}

            def _telegram_resolver(app_id: str) -> EngineToolBinding | None:
                grant = effective_telegram_grants.get(app_id)
                if grant is None:
                    return None
                cached = cache.get(app_id)
                if cached is not None:
                    return cached
                binding = telegram_tool_binding(grant=grant, port=telegram_port)
                cache[app_id] = binding
                return binding

            telegram_resolver = _telegram_resolver

    if gmail_resolver is None and drive_resolver is None and telegram_resolver is None:
        return None

    def _resolver(app_id: str) -> EngineToolBinding | None:
        if gmail_resolver is not None:
            binding = gmail_resolver(app_id)
            if binding is not None:
                return binding
        if drive_resolver is not None:
            binding = drive_resolver(app_id)
            if binding is not None:
                return binding
        if telegram_resolver is not None:
            return telegram_resolver(app_id)
        return None

    return _resolver


__all__ = [
    "DRIVE_AGENT_ID",
    "DRIVE_REFERENCE_APP_ID",
    "GMAIL_CONNECTOR_ID",
    "GMAIL_MAIL_READER_AGENT_ID",
    "GMAIL_REFERENCE_APP_ID",
    "TELEGRAM_AGENT_ID",
    "TELEGRAM_CONNECTOR_ID",
    "TELEGRAM_REFERENCE_APP_ID",
    "DriveGrant",
    "GmailGrant",
    "TelegramGrant",
    "build_tool_binding_resolver",
    "drive_tool_binding",
    "gmail_tool_binding",
    "telegram_tool_binding",
]
