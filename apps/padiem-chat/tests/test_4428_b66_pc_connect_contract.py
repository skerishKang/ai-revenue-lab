"""#4428 B66 Connect: static, security and no-premature-activation contract."""
import json

from _support.b66_pc_connect import (
    AUTH_EVENTS,
    ENTITLEMENT_EXPRESSIONS,
    EXPECTED_IDS,
    LIFECYCLE_EXPRESSIONS,
    LOADER_ALLOWED,
    UNAVAILABLE_COPY,
    runtime_facts,
    script_order,
    server_facts,
)


def test_b66_pc_view_reuses_canonical_claw_projection_without_execution():
    js = runtime_facts()
    assert set(EXPECTED_IDS).issubset(js["element_ids"])
    assert js["directory_path"] == ("/api/b66/connect/devices",)
    assert js["handoff_projection"] is True
    scripts = script_order()
    assert scripts.index("./claw-local-handoff.js") < scripts.index("./b66-quote-runtime.js")
    assert js["credentials"] == ("same-origin",)
    # #5895-D: no client byte gate refuses the owner's own same-origin reads.
    assert js["byte_gate_present"] is False
    assert js["json_parse_payload"] is True
    assert js["loader_methods"] == ("GET",)
    assert set(LOADER_ALLOWED).issubset(js["loader_present"])
    assert js["loader_forbidden"] == ()
    assert js["entitlement_present"][:3] == ENTITLEMENT_EXPRESSIONS[:3]


def test_no_eager_request_and_logout_discards_stale_pc_results():
    js = runtime_facts()
    assert set(LIFECYCLE_EXPRESSIONS).issubset(js["lifecycle_present"])
    assert js["auth_event_arrays"] == (json.dumps(list(AUTH_EVENTS)),)
    # #6100: the same capability event sets signedIn (the logged-out hint)
    # and refreshes only for a signed-in browser.
    assert js["logout_reset"] is True
    assert set(UNAVAILABLE_COPY).issubset(js["unavailable_copy"])
    assert js["loader_external_url"] is False


def test_b66_pc_directory_is_default_off_without_product_entitlement():
    """No B66 product permission adapter is live yet; do not leak Claw devices."""
    js = runtime_facts()
    assert set(ENTITLEMENT_EXPRESSIONS).issubset(js["entitlement_present"])
    facts = server_facts()
    assert len(facts["server_present"]) == 2
    assert len(facts["gate_present"]) == 5
