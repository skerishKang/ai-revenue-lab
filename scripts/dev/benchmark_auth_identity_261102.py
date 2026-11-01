"""#6612 — where login spends its identity time, and what each shape is worth.

Every number here comes from the real bridge functions
(`bridge_trusted_product_auth`, `bridge_trusted_b54_server_auth`) against an
authority whose every RPC costs 120 ms. That is the cost implied by the round-4
journal: 6,721 ms of identity time for a password login, which runs six serial
RPCs today.

Shapes measured:

* ``serial`` — today: B62 link, B62 memberships, B62 session, then B54 link,
  B54 memberships, B54 session.
* ``both-parallel`` — the two product chains overlap. Unsafe as-is: on a first
  login both would see zero memberships and each provision a personal tenant.
* ``parallel + memo`` — both chains overlap while a request-scoped memo answers
  the second membership read. Also unsafe as-is: B54's bridge is pinned to take
  no caller value (see the doc).

So this script is evidence, not a proposal: it prices the shapes a future
authorized slice may choose, and shows why none of them may be taken here.

    python scripts/dev/benchmark_auth_identity_261102.py
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/padiem-control-plane"))
sys.path.insert(0, str(ROOT / "apps/padiem-chat"))

from padiem_control_plane import (  # noqa: E402
    AuthSessionSnapshot,
    AuthSessionState,
    IdentityLinkState,
    ProductIdentityLink,
)
from padiem_control_plane.b54_identity_bridge import (  # noqa: E402
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
)
from app.control_plane_identity import (  # noqa: E402
    TrustedProductAuthEvidence,
    bridge_trusted_product_auth,
)

RPC_MS = 120
TENANT = "tnt_benchmark"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class SlowAuthority:
    """Every identity RPC costs RPC_MS; the calls are counted per method."""

    def __init__(self, memberships: tuple[str, ...] = (TENANT,)) -> None:
        self.memberships = memberships
        self.calls: list[str] = []

    async def _cost(self, name: str) -> None:
        # Awaited, like the real Service Binding RPC: a blocking sleep would make
        # gather() look useless and hide the whole point of the measurement.
        self.calls.append(name)
        await asyncio.sleep(RPC_MS / 1000)

    async def resolve_or_create_product_link(self, **kwargs):
        await self._cost("link")
        return ProductIdentityLink(
            product_id=kwargs["product_id"],
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id="subject:" + kwargs["product_id"],
            state=IdentityLinkState.ACTIVE,
        )

    async def resolve_active_memberships(self, *, canonical_subject_id: str):
        await self._cost("memberships")
        return self.memberships

    async def create_tenant(self) -> str:
        await self._cost("create_tenant")
        self.memberships = (TENANT,)
        return TENANT

    async def assign_tenant_membership(self, *, tenant_id: str, canonical_subject_id: str) -> None:
        await self._cost("assign")

    async def establish_auth_session(self, **kwargs):
        await self._cost("session")
        return AuthSessionSnapshot(
            session_id="sess_benchmark",
            product_id=kwargs["product_id"],
            subject=kwargs["subject"],
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT,
        )


class MemoAuthority(SlowAuthority):
    """A request-scoped membership memo: the second read of the subject is free."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: dict[str, tuple[str, ...]] = {}

    async def resolve_active_memberships(self, *, canonical_subject_id: str):
        if canonical_subject_id in self._seen:
            self.calls.append("memberships(memo)")
            return self._seen[canonical_subject_id]
        memberships = await super().resolve_active_memberships(
            canonical_subject_id=canonical_subject_id)
        self._seen[canonical_subject_id] = memberships
        return memberships


B62_EVIDENCE = TrustedProductAuthEvidence(
    product_user_id="usr_benchmark", provider="password",
    provider_subject="owner@example.test",
    authenticated_at=NOW, expires_at=NOW + timedelta(hours=1),
)


def _b54_evidence() -> TrustedB54ServerAuthEvidence:
    return TrustedB54ServerAuthEvidence(
        product_user_id="usr_benchmark", provider="password",
        provider_subject="owner@example.test",
        authenticated_at=NOW, expires_at=NOW + timedelta(hours=1),
    )


async def _b62(authority):
    return await bridge_trusted_product_auth(
        authority, B62_EVIDENCE, now=NOW, ensure_personal_tenant=True)


async def _b54(authority):
    return await bridge_trusted_b54_server_auth(authority, _b54_evidence(), now=NOW)


async def login_serial(authority) -> None:
    await _b62(authority)
    await _b54(authority)


async def login_both_parallel(authority) -> None:
    await asyncio.gather(_b62(authority), _b54(authority))


def measure(label: str, shape, authority_factory=SlowAuthority, runs: int = 5) -> str:
    samples, calls = [], 0
    for _ in range(runs):
        authority = authority_factory()
        started = time.perf_counter()
        asyncio.run(shape(authority))
        samples.append((time.perf_counter() - started) * 1000.0)
        calls = len(authority.calls)
    ordered = sorted(samples)
    return (f"{label:<18} rpc={calls} avg={statistics.fmean(samples):7.1f}ms "
            f"p50={statistics.median(samples):7.1f}ms max={ordered[-1]:7.1f}ms")


def main() -> int:
    print(f"one identity RPC = {RPC_MS} ms\n")
    serial = measure("login serial", login_serial)
    parallel = measure("login parallel", login_both_parallel)
    memo = measure("parallel + memo", login_both_parallel, MemoAuthority)
    print(serial)
    print(parallel)
    print(memo)
    print("\nrefresh (/auth/shared/refresh) — the #6573 account-link cache is already used:")
    print(f"  link row warm: 0 identity RPC (one SQLite read)")
    print(f"  link row cold: 1 identity RPC = ~{RPC_MS} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
