"""#7541 — every registered common-login client can start a first login.

The common login asks the identity authority for an account number the first
time it sees a person, and sends the client id as the product id. A registered
client the authority does not admit therefore fails every first login with a
503, while accounts that already exist keep working — which is how BookAI went
unnoticed: it was checked with an existing account.

This runs every registered client through the real authority, built by its own
constructor, with no fake in between. A client is either admitted, or it is
listed with a reason in the exclusion file the common-login tests also read.

It reads two Worker config files by name, and the foundation package gate
refuses that name in any .py under packages/padiem-control-plane, so it lives
here beside the other identity config assertions.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "packages" / "padiem-control-plane"
AUTH_ROOT = ROOT / "apps" / "padiem-auth"
sys.path.insert(0, str(PACKAGE_ROOT / "tests"))

from test_bookai_identity_registration import MISMATCH, authority, link  # noqa: E402

REGISTERED_CLIENTS = sorted(
    json.loads(
        tomllib.loads((AUTH_ROOT / "wrangler.toml").read_text(encoding="utf-8"))["vars"]["PADIEM_AUTH_CLIENTS"]
    )
)
NOT_AN_IDENTITY_PRODUCT = json.loads(
    (AUTH_ROOT / "test" / "identity-product-exclusions.json").read_text(encoding="utf-8")
)


def _reviewed(name: str) -> frozenset[str]:
    source = (PACKAGE_ROOT / "identity_authority_worker.py").read_text(encoding="utf-8")
    found = re.search(name + r": frozenset\[str\] = frozenset\(\{([^}]*)\}\)", source)
    assert found is not None, name
    return frozenset(value.strip().strip("\"'") for value in found.group(1).split(",") if value.strip())


def test_every_registered_client_is_admitted_or_excluded_with_a_reason() -> None:
    assert REGISTERED_CLIENTS, "no registered common-login client was read"
    for client_id, reason in NOT_AN_IDENTITY_PRODUCT.items():
        assert client_id in REGISTERED_CLIENTS, client_id
        assert isinstance(reason, str) and len(reason) > 40, client_id

    for client_id in REGISTERED_CLIENTS:
        # A fresh authority and a fresh person per client: the first login.
        answer = link(authority(), product=client_id, subject=f"first-login-{client_id}")
        if client_id in NOT_AN_IDENTITY_PRODUCT:
            assert answer["ok"] is False, client_id
            assert answer["error"]["code"] == MISMATCH, client_id
            continue
        # The exact shape the common login requires before it accepts the account.
        assert answer["ok"] is True, client_id
        assert answer["link"]["state"] == "active", client_id
        assert answer["link"]["product_id"] == client_id, client_id
        assert re.fullmatch(r"sub_[A-Za-z0-9_-]+", answer["link"]["canonical_subject_id"]), client_id


def test_the_deployed_product_list_equals_the_reviewed_set() -> None:
    # The authority refuses to start when these differ, and nothing but a live
    # request finds that out after a deploy. Both instances are checked here.
    config = json.loads((PACKAGE_ROOT / "wrangler.identity-authority.jsonc").read_text(encoding="utf-8"))
    reviewed = _reviewed("_ALLOWED_PRODUCTS")
    for name, variables in (("production", config["vars"]), ("staging", config["env"]["staging"]["vars"])):
        assert variables["CONTROL_PLANE_CONNECTOR_ACCOUNT_KEY_WRITE_RPC_ENABLED"] == "false", name
        deployed = [item.strip() for item in variables["CONTROL_PLANE_ALLOWED_PRODUCTS"].split(",")]
        assert len(deployed) == len(set(deployed)), name
        assert frozenset(deployed) == reviewed, name
        removal = variables["CONTROL_PLANE_LINK_REMOVAL_PRODUCTS"].split(",")
        assert len(removal) == len(set(removal)), name
        assert frozenset(removal) == _reviewed("_LINK_REMOVAL_PRODUCTS"), name
    assert _reviewed("_LINK_ONLY_PRODUCTS") <= reviewed
    assert _reviewed("_LINK_REMOVAL_PRODUCTS") <= reviewed


def test_log_retention_keeps_own_lines_without_automatic_invocation_logs() -> None:
    # #7542 P0-C: automatic invocation logs could record sign-in URLs (one-time
    # codes) and request headers (the relay secret), so only the Worker's own
    # lines are kept. The identity authority stays as its own gates pin it.
    import tomllib

    reviewed = {"enabled": True, "head_sampling_rate": 1, "logs": {"invocation_logs": False}}
    for app in ("padiem-auth", "lovetree-auth-caller", "lovetree-authority-caller"):
        worker = tomllib.loads((ROOT / "apps" / app / "wrangler.toml").read_text(encoding="utf-8"))
        assert worker["observability"] == reviewed, app

