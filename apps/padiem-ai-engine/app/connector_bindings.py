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
    GmailReadPort,
    GMAIL_CANONICAL_TOOL_IDS,
    GMAIL_CONNECTOR_ID,
    ToolAuthorizationContext,
    ToolRegistrySnapshot,
    ToolResourcePolicy,
    ToolRuntime,
    ToolRuntimeBinding,
    TrustedAgentRuntimePolicy,
    compile_agent_profile,
    gmail_read_tool_specs,
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


def build_tool_binding_resolver(
    *,
    gmail_port: GmailReadPort | None,
    grants: Mapping[str, GmailGrant] | None = None,
    grants_loader: Callable[[], Awaitable[Mapping[str, GmailGrant]]] | None = None,
) -> Callable[[str], EngineToolBinding | None] | None:
    """Build the cached per-app_id resolver the composition root injects.

    * ``gmail_port is None`` ⇒ ``None``. The composition stays fail-closed
      (``tool_runtime_unavailable``) exactly as it was in the WO-1 source
      seam.

    * ``grants`` is a pre-resolved mapping. ``grants_loader`` is an async
      factory that the caller may supply when grants come from an async
      source (e.g., D1). When both are provided, ``grants`` wins.

    * When either ``gmail_port`` or the effective grants mapping is empty,
      the resolver is ``None``.
    """
    if gmail_port is None:
        return None
    effective_grants = grants
    if effective_grants is None and grants_loader is not None:
        # grants_loader is async; the resolver is sync. The caller must
        # pre-resolve grants before passing them. Until then, fail-closed.
        effective_grants = {}
    if not effective_grants:
        return None

    cache: dict[str, EngineToolBinding] = {}

    def resolver(app_id: str) -> EngineToolBinding | None:
        grant = effective_grants.get(app_id)
        if grant is None:
            return None
        cached = cache.get(app_id)
        if cached is not None:
            return cached
        binding = gmail_tool_binding(grant=grant, port=gmail_port)
        cache[app_id] = binding
        return binding

    return resolver


__all__ = [
    "GMAIL_CONNECTOR_ID",
    "GMAIL_MAIL_READER_AGENT_ID",
    "GMAIL_REFERENCE_APP_ID",
    "GmailGrant",
    "build_tool_binding_resolver",
    "gmail_tool_binding",
]
