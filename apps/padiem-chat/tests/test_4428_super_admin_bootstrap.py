"""#4428: global server bootstrap never mints admin by browser identity."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.padiem_super_admin_bootstrap import resolve_super_admin_bootstrap as resolve


def test_global_operator_maps_to_b66_and_central_without_product_bindings():
    assert resolve(shared="  OWNER@PADIEM.NET  ", legacy_b66=None, legacy_central=None) == (
        "owner@padiem.net", "owner@padiem.net",
    )


def test_matching_legacy_bindings_preserve_exact_global_operator():
    assert resolve(
        shared="owner@padiem.net",
        legacy_b66="OWNER@PADIEM.NET",
        legacy_central=" owner@padiem.net ",
    ) == ("owner@padiem.net", "owner@padiem.net")


@pytest.mark.parametrize("legacy", [
    "another@padiem.net", "owner@padiem.net\\nX-Admin:true",
    "not-an-email", 1234,
])
def test_conflicting_or_invalid_legacy_binding_blocks_both_products(legacy):
    assert resolve(
        shared="owner@padiem.net", legacy_b66=legacy, legacy_central=None,
    ) == ("", "")
    assert resolve(
        shared="owner@padiem.net", legacy_b66=None, legacy_central=legacy,
    ) == ("", "")


@pytest.mark.parametrize("shared", [
    "", "  ", "not-an-email", "owner@invalid", "user@example.com\\nrole=admin",
    1, {"email": "owner@padiem.net"}, "x" * 256 + "@padiem.net",
])
def test_bad_shared_binding_never_falls_back_to_legacy(shared):
    assert resolve(
        shared=shared, legacy_b66="owner@padiem.net",
        legacy_central="owner@padiem.net",
    ) == ("", "")


def test_legacy_compatibility_is_isolated_until_shared_binding_is_provisioned():
    assert resolve(
        shared=None, legacy_b66="b66@example.test",
        legacy_central="central@example.test",
    ) == ("b66@example.test", "central@example.test")
    assert resolve(shared=None, legacy_b66=None, legacy_central=None) == ("", "")


def test_no_role_or_browser_authority_added_at_worker_entrypoint():
    worker = (Path(__file__).parents[1] / "worker.py").read_text(encoding="utf-8")
    assert 'binding_value(self.env, "PADIEM_SUPER_ADMIN_GOOGLE_EMAIL")' in worker
    assert "b66_admin_google_email=b66_operator_email" in worker
    assert "central_model_admin_google_email=central_operator_email" in worker
    assert "request.query_params" not in worker[worker.index("b66_operator_email, central_operator_email"):worker.index("_worker_app = create_app")]


def test_product_authorizers_still_validate_immutable_google_subject():
    root = Path(__file__).parents[1] / "app"
    central = (root / "central_model_admin_identity.py").read_text(encoding="utf-8")
    b66 = (root / "b66_member_admin.py").read_text(encoding="utf-8")
    for auth in (central, b66):
        assert "u.auth_provider='google'" in auth
        assert "pc.user_id IS NULL" in auth
        assert "_user_id(subject) == user_id" in auth
        assert "password:" in auth
