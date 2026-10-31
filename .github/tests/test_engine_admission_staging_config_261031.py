"""The engine-admission staging instance is its own Worker with its own namespace.

This assertion reads the Worker config file by name, and the foundation package
gate refuses that name in any .py under packages/padiem-control-plane, so the
test lives here instead of beside the other ingress contracts. It was moved
verbatim; the reviewed assertions are unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"


def test_the_staging_instance_is_its_own_worker_with_its_own_namespace() -> None:
    config = json.loads(
        (PACKAGE_ROOT / "wrangler.engine-admission-authority.jsonc").read_text(
            encoding="utf-8"
        )
    )
    staging = config["env"]["staging"]

    assert config["name"] == "padiem-control-plane-engine-admission"
    assert config["workers_dev"] is False
    assert staging["name"] == "padiem-control-plane-engine-admission-staging"
    assert staging["name"] != config["name"]
    # workers.dev only: no zone route may exist on the staging instance.
    assert staging["workers_dev"] is True
    assert "routes" not in staging and "routes" not in config
    # Its own Durable Object namespace, same reviewed class and binding name.
    assert staging["durable_objects"] == config["durable_objects"]
    # Staging never reads the production identity authority.
    staging_identity = {
        entry["binding"]: entry["service"] for entry in staging["services"]
    }
    assert staging_identity["CONTROL_PLANE_IDENTITY"] != "padiem-control-plane-identity"
    # Same reviewed product boundary in both instances.
    assert staging["vars"] == config["vars"]
