from __future__ import annotations

from _support.capability_navigation import (
    app_factory_facts,
    const_expression,
    deployment_projection,
    function_view,
    index_buttons,
    index_document_position,
    index_ids,
    index_script_attrs,
    search_sources_export,
    source_view,
    tier_copy_by_lang,
)


FLAGS = (
    "web_tools_ready",
    "deep_research_ready",
    "auth_configured",
    "history_store_bound",
    "projects_code_ready",
    "project_files_code_ready",
    "project_file_store_bound",
    "saved_outputs_code_ready",
    "saved_output_store_bound",
)
COMPOSER_CONTROLS = ("webSearchButton", "webSearchStarterButton", "deepResearchButton")


def test_only_login_is_a_deployment_conditional_primary_control():
    buttons = index_buttons()
    assert "loginButton" in buttons
    assert "hidden" in buttons["loginButton"]
    assert "disabled" in buttons["loginButton"]
    assert buttons["loginButton"].get("aria-disabled") == "true"
    assert not ({"webSearchStarterButton", "webSearchButton", "deepResearchButton"} & buttons.keys())
    assert "projectsNavButton" not in index_ids()


def test_browser_capability_projection_is_bounded_visibility_not_execution_authority() -> None:
    cap = source_view("product-capabilities.js")
    assert '"/health"' in cap["fetch_first_args"]
    assert '"/api/auth/status"' in cap["fetch_first_args"]
    for flag in FLAGS:
        assert flag in cap["identifiers"]
    assert any(
        callee == "CustomEvent" and args.startswith('"padiem:capabilitychange"')
        for callee, args in cap["call_args"]
    )
    assert "Object.freeze" in cap["member_chains"]
    # #5121: the custom credential metadata endpoints exist, but chat execution
    # must stay out of this projection.
    assert '"/api/chat"' not in cap["string_literals"]
    assert '"/api/chat/stream"' not in cap["string_literals"]
    assert "payload.tool" not in cap["member_chains"]
    assert "localStorage" not in cap["identifiers"]
    assert "sessionStorage" not in cap["identifiers"]
    assert "document.cookie" not in cap["member_chains"]


def test_search_capabilities_remain_server_projected_without_composer_controls():
    cap = source_view("product-capabilities.js")
    search = source_view("search-sources.js")
    html_ids = set(index_ids())
    for identifier in COMPOSER_CONTROLS:
        assert identifier not in html_ids
        assert identifier not in cap["identifiers"]
        assert identifier not in search["identifiers"]
    for flag in ("web_tools_ready", "deep_research_ready"):
        assert flag in cap["identifiers"]
    assert "window.PadiemSearchSources" in search["member_chains"]


def test_sidebar_search_is_an_independent_fail_closed_conversation_search_entry() -> None:
    buttons = index_buttons()
    search = buttons["sidebarSearchButton"]
    # Visible on the second sidebar line beside New Chat. #4471: it opens real
    # conversation search but stays disabled in markup until history is ready.
    assert "hidden" not in search
    assert "disabled" in search
    assert search.get("aria-disabled") == "true"
    assert (
        index_document_position("newChatButton")
        < index_document_position("sidebarSearchButton")
        < index_document_position("side-nav")
    )
    assert any(
        attrs.get("src") == "./conversation-search.js" and "defer" in attrs
        for attrs in index_script_attrs()
    )


def test_sidebar_search_is_separate_from_result_rendering():
    cap = source_view("product-capabilities.js")
    conversation_search = source_view("conversation-search.js")
    has_sidebar_lookup = lambda view: any(
        callee.endswith("getElementById") and '"sidebarSearchButton"' in args
        for callee, args in view["call_args"]
    )
    assert not has_sidebar_lookup(cap)
    assert "syncSidebarSearch" not in cap["identifiers"]
    assert has_sidebar_lookup(conversation_search)
    vocabulary = (
        conversation_search["identifiers"]
        | conversation_search["string_literals"]
        | conversation_search["member_chains"]
    )
    for forbidden in COMPOSER_CONTROLS:
        assert not any(forbidden in token for token in vocabulary)
    search = source_view("search-sources.js")
    assert "sidebarSearchButton" not in search["identifiers"]
    assert search_sources_export() == {
        "frozen": True,
        "keys": ["render"],
        "values": ["renderSources"],
    }


def test_auth_status_controls_account_session_visibility_while_health_controls_code_capability() -> None:
    projection = deployment_projection()
    assert projection["projects"] == "bool(data.projects_code_ready)"
    assert projection["projectFiles"] == (
        "bool(data.project_files_code_ready) && bool(data.project_file_store_bound)"
    )
    assert projection["savedOutputs"] == (
        "bool(data.saved_outputs_code_ready) && bool(data.saved_output_store_bound)"
    )
    assert const_expression("product-capabilities.js", "authAvailable") == (
        'auth.loaded && auth.ready && auth.sessionState !== "unavailable"'
    )
    visibility = function_view("product-capabilities.js", "syncAccountVisibility")
    assert {"deployment.projects", "auth.authenticated", "auth.historyReady"} <= visibility["member_chains"]
    assert "syncAccountPresentation" in visibility["calls"]
    assert ("setHidden", "projectsNavButton, !projectsAvailable") in visibility["call_args"]

    server = app_factory_facts()
    assert ("/health", ("GET",)) in server["routes"]
    entries = server["capability_entries"]
    assert entries["web_tools_ready"] == "web_ready"
    assert entries["deep_research_ready"] == "research_ready"
    assert entries["auth_configured"] == (
        'settings.auth_mode != "off" or getattr(request.app.state, "shared_login_flow", None) is not None'
    )
    assert entries["history_store_bound"] == "request.app.state.history_store is not None"


def test_capability_projection_only_mutates_the_custom_credential_surface() -> None:
    cap = source_view("product-capabilities.js")
    # #5824 permits only the two owner-authenticated BYOK verification POSTs.
    auto = function_view("product-capabilities.js", "detectAndRegister")
    assert auto["method_counts"] == {"POST": 2}
    assert '"/api/byok/detect"' in auto["fetch_first_args"]
    assert '"/api/byok/register"' in auto["fetch_first_args"]
    assert ("credentials", "same-origin") in auto["property_pairs"]
    assert auto["call_counts"].get("JSON.stringify") == 2
    assert cap["method_counts"]["POST"] == auto["method_counts"]["POST"]
    assert cap["method_counts"].get("PATCH", 0) == 0
    # #5121: exactly one DELETE, scoped to the custom credential route, no body.
    delete = function_view("product-capabilities.js", "deleteCustomKey")
    assert cap["method_counts"].get("DELETE", 0) == 1
    assert delete["method_counts"] == {"DELETE": 1}
    assert delete["fetch_first_args"] == {
        '"/api/chat/custom/credential?provider=" + encodeURIComponent(provider.provider)'
    }
    assert (
        "/api/chat/custom/credential?provider=",
        "encodeURIComponent(provider.provider)",
    ) in delete["string_plus_calls"]
    assert "body" not in delete["property_names"]
    vocabulary = cap["identifiers"] | cap["string_literals"] | cap["member_chains"]
    assert not any(forbidden in token.lower() for token in vocabulary for forbidden in ("b14", "control_plane"))


def test_dead_window_exports_and_flat_tier_copy_admin_labels() -> None:
    dead_exports = {
        "claw-mesh-capture.js": "window.PadiemClawMeshCapture",
        "claw-office-chooser.js": "window.PadiemHarkOfficeChooser",
        "conversation-search.js": "window.PadiemConversationSearch",
    }
    for filename, symbol in dead_exports.items():
        view = source_view(filename)
        vocabulary = view["member_chains"] | view["string_literals"] | view["identifiers"]
        assert not any(symbol in token for token in vocabulary), (filename, symbol)

    tiers = tier_copy_by_lang()
    assert tiers["ko"]["admin"] == "Padiem 관리자"
    assert tiers["en"]["admin"] == "Padiem Admin"
    assert tiers["ko"]["admin"] not in tiers["en"]["admin"]
