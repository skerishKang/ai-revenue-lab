"""Request-only opaque Chat credential forwarding; never a credential store."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from collections.abc import Mapping

_REF = ContextVar("engine_user_credential_ref", default=None)
FIELD = "user_credential_ref"


def split_credential(payload):
    if not isinstance(payload, Mapping):
        return payload, None
    ref = payload.get(FIELD)
    policy = payload.get("agent", {}).get("model_policy", {}) if isinstance(payload.get("agent"), Mapping) else {}
    required = isinstance(policy, Mapping) and policy.get("user_credential_required") is True
    if FIELD not in payload and not required:
        return payload, None
    if FIELD not in payload and required:
        ref = _REF.get()
    if (payload.get("app_id") != "padiem-chat" or not isinstance(ref, str) or not ref
            or not required or not payload.get("subject_id")):
        raise ValueError("User credential reference is required for this execution.")
    return {k: v for k, v in payload.items() if k != FIELD}, ref


@contextmanager
def credential_scope(ref):
    token = _REF.set(ref)
    try:
        yield
    finally:
        _REF.reset(token)


def b14_body(raw):
    ref = _REF.get()
    if ref is None:
        return raw
    # Only the B14 body shape is decoded. The reference itself is not parsed.
    data = json.loads(raw)
    data[FIELD] = ref
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def safe_cause(exc):
    # A binding implementation can quote its request body on failure. Preserve
    # the exact legacy exception chain only when no user reference is present.
    return None if _REF.get() is not None else exc


def core_model_policy(policy):
    if policy.get('user_credential_required') is not True:
        return policy
    # These are product replay markers, not model options. Core's closed
    # model-policy contract must never see them or the opaque credential.
    return {**{k: v for k, v in policy.items()
               if k not in {'user_credential_required', 'byok_selection'}},
            'max_retries': 0}


def core_request(request):
    from dataclasses import replace
    policy = core_model_policy(request.agent.model_policy)
    if policy is request.agent.model_policy:
        return request
    return replace(request, agent=replace(request.agent, model_policy=policy))


class UserCredentialRuntime:
    def __init__(self, runtime):
        self.runtime = runtime

    def __getattr__(self, name):
        return getattr(self.runtime, name)

    async def run(self, request):
        return await self.runtime.run(core_request(request))
