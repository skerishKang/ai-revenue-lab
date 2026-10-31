"""The staging identity instance is its own Worker and names no production state.

This assertion reads the Worker config file by name, and the foundation package
gate refuses that name in any .py under packages/padiem-control-plane, so the
test lives here instead of beside the verifier contracts. It was moved
verbatim; the reviewed assertions are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"


def test_the_staging_identity_is_its_own_worker_and_names_no_production_state() -> None:
    config = json.loads(
        (PACKAGE_ROOT / "wrangler.identity-authority.jsonc").read_text(encoding="utf-8")
    )
    staging = config["env"]["staging"]
    text = json.dumps(staging)

    assert config["name"] == "padiem-control-plane-identity"
    assert config["workers_dev"] is True
    assert config["preview_urls"] is False
    assert staging["preview_urls"] is False
    assert staging["name"] == "padiem-control-plane-identity-staging"
    assert staging["workers_dev"] is True
    assert "routes" not in staging and "routes" not in config
    assert staging["durable_objects"] == config["durable_objects"]
    # Nothing in staging names the production Worker or its authority domain.
    assert "control-plane.identity.production" not in text
    assert staging["name"] not in text.replace(staging["name"], "", 1)
    assert staging["vars"]["PADIEM_RPC_SERVICE_ID_POLICY"] == "required"
    assert set(config["secrets"]["required"]) <= set(staging["secrets"]["required"])
