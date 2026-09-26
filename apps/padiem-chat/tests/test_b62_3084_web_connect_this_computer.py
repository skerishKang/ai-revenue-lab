"""#3084 — Web/B62 "Connect this computer" handoff.

Scope of this suite: deterministic client projection + presentation only.
It asserts the non-authority contract as hard as it asserts the UX contract,
because the point of #3084 is that Web owns *none* of the following while
#3080 is still in flight: pairing, device session, transport, task admission,
approval decision, execution.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TESTS = ROOT / "tests"

MODULE_PATH = STATIC / "claw-local-handoff.js"
MODULE_CSS = STATIC / "claw-local-handoff.css"
APP_PATH = STATIC / "app.js"
INDEX_PATH = STATIC / "index.html"
LOCALE_PATH = STATIC / "locale.js"


def _source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


def _app_source() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _index_source() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _locale_source() -> str:
    return LOCALE_PATH.read_text(encoding="utf-8")


def _run_node(script: str) -> str:
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _harness(body: str) -> str:
    """Load the real module into a fake window, then evaluate `body`."""
    module = _source()
    return (
        "global.window = globalThis;\n"
        + module
        + "\nconst H = global.window.PadiemClawLocalHandoff;\n"
        + body
    )


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. Module contract / non-authority
# ---------------------------------------------------------------------------


def test_module_is_a_plain_browser_iife_without_transport_authority() -> None:
    source = _source()
    assert 'window.PadiemClawLocalHandoff' in source
    for forbidden in (
        "new WebSocket",
        "EventSource",
        "navigator.serviceWorker",
        "indexedDB",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "crypto.subtle",
        "atob(",
        "btoa(",
        "jwt",
        "JSON.parse(",
    ):
        assert forbidden not in source, f"transport/credential authority leaked: {forbidden}"


def test_module_makes_no_network_call_of_any_kind() -> None:
    source = _source()
    for forbidden in ("fetch(", "XMLHttpRequest", "/api/", "http://", "https://"):
        assert forbidden not in source, f"network call leaked into the projection: {forbidden}"


def test_module_declares_the_canonical_device_states() -> None:
    states = json.loads(
        _run_node(
            _harness("console.log(JSON.stringify(H.CANONICAL_DEVICE_STATES));")
        )
    )
    assert states == ["PAIRING", "CONNECTED", "OFFLINE", "REVOKED", "ACTION_REQUIRED"]


def test_module_exposes_only_projection_surface() -> None:
    keys = json.loads(
        _run_node(
            _harness(
                "console.log(JSON.stringify(Object.keys(H).sort()));"
            )
        )
    )
    for required in (
        "CONTRACT_VERSION",
        "CANONICAL_DEVICE_STATES",
        "normalizeDeviceProjection",
        "consumeHandoffEnvelope",
        "deriveHandoffViewModel",
        "shouldSubmitOnEnter",
        "createCompositionGuard",
        "copy",
        "projectHandoffPanel",
        "FIXTURES",
    ):
        assert required in keys
    # No minting/transport/approval API may be exported.
    for forbidden in (
        "createPairingToken",
        "mintToken",
        "signPairing",
        "openTransport",
        "connect",
        "admitTask",
        "approve",
        "execute",
        "createDeviceSession",
    ):
        assert forbidden not in keys


# ---------------------------------------------------------------------------
# 2. local-access-required state
# ---------------------------------------------------------------------------


def test_local_access_required_projection_shows_the_panel() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.installRequired);"
            "console.log(JSON.stringify({requiresLocalAccess: m.requiresLocalAccess,"
            " installState: m.installState, canProceed: m.canProceed}));"
        )
    )
    data = json.loads(out)
    assert data["requiresLocalAccess"] is True
    assert data["installState"] == "install_required"
    # Not usable yet: device is offline.
    assert data["canProceed"] is False


def test_no_local_access_requirement_keeps_the_panel_hidden() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'c1',"
            " requiresLocalAccess: false, device: {state: 'CONNECTED', usable: true}});"
            "console.log(JSON.stringify({requiresLocalAccess: m.requiresLocalAccess}));"
        )
    )
    assert json.loads(out)["requiresLocalAccess"] is False


def test_capability_list_alone_can_signal_local_access() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'c1',"
            " requiredCapabilities: ['local_computer']});"
            "console.log(String(m.requiresLocalAccess));"
        )
    )
    assert out == "true"


# ---------------------------------------------------------------------------
# 3. Desktop install / open handoff
# ---------------------------------------------------------------------------


def test_install_path_fixture_offers_install_guidance_not_open() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.installRequired);"
            "console.log(JSON.stringify({installState: m.installState,"
            " desktopInstalled: m.desktopInstalled,"
            " cta: H.ctaLabel(m, 'en')}));"
        )
    )
    data = json.loads(out)
    assert data["installState"] == "install_required"
    assert data["desktopInstalled"] is False
    assert data["cta"] == "See install instructions"


def test_installed_path_fixture_offers_open() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.connected);"
            "console.log(JSON.stringify({installState: m.installState,"
            " cta: H.ctaLabel(m, 'en')}));"
        )
    )
    data = json.loads(out)
    assert data["installState"] == "installed"
    assert data["cta"] == "Open this computer"


# ---------------------------------------------------------------------------
# 4. Opaque handoff value — consumer seam only
# ---------------------------------------------------------------------------


def test_opaque_handoff_value_is_consumed_not_parsed() -> None:
    out = _run_node(
        _harness(
            "const h = H.consumeHandoffEnvelope({kind: 'deep_link', value: ' opaque-abc-123 '});"
            "console.log(JSON.stringify({available: h.available, value: h.value, kind: h.kind}));"
        )
    )
    data = json.loads(out)
    assert data == {"available": True, "value": "opaque-abc-123", "kind": "deep_link"}


def test_absent_or_malformed_handoff_is_not_offered() -> None:
    out = _run_node(
        _harness(
            "console.log(JSON.stringify(["
            " H.consumeHandoffEnvelope({kind: 'deep_link'}),"
            " H.consumeHandoffEnvelope({kind: 'deep_link', value: 42}),"
            " H.consumeHandoffEnvelope({kind: 'browser_extension', value: 'x'}),"
            " H.consumeHandoffEnvelope(null)"
            "].map((h) => ({available: h.available, reason: h.reason, value: h.value}))));"
        )
    )
    data = json.loads(out)
    assert all(item["available"] is False for item in data)
    assert all(item["value"] is None for item in data)
    reasons = {item["reason"] for item in data}
    assert reasons == {"absent", "malformed", "unsupported_kind"}


def test_handoff_without_value_blocks_proceed_even_when_connected() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'c1', requiresLocalAccess: true,"
            " desktopInstalled: true, device: {state: 'CONNECTED', usable: true}, handoff: {}});"
            "console.log(String(m.canProceed));"
        )
    )
    assert out == "false"


# ---------------------------------------------------------------------------
# 5. Truthful device states
# ---------------------------------------------------------------------------


def test_each_canonical_state_projects_to_its_own_presentation() -> None:
    out = _run_node(
        _harness(
            "const states = ['PAIRING', 'CONNECTED', 'OFFLINE', 'REVOKED', 'ACTION_REQUIRED'];"
            "console.log(JSON.stringify(states.map((s) => {"
            "  const d = H.normalizeDeviceProjection({state: s, usable: s === 'CONNECTED'});"
            "  const m = H.deriveHandoffViewModel({conversationId: 'c1', requiresLocalAccess: true,"
            "   desktopInstalled: true, device: {state: s, usable: s === 'CONNECTED'},"
            "   handoff: {kind: 'deep_link', value: 'v'}});"
            "  return {state: d.state, usable: d.usable, showConnected: m.showConnected,"
            "   canProceed: m.canProceed, label: H.deviceStateLabel(m, 'en')};"
            "})));"
        )
    )
    rows = json.loads(out)
    by_state = {row["state"]: row for row in rows}
    assert set(by_state) == {
        "PAIRING",
        "CONNECTED",
        "OFFLINE",
        "REVOKED",
        "ACTION_REQUIRED",
    }
    # Only CONNECTED is usable and only CONNECTED can proceed.
    for state, row in by_state.items():
        if state == "CONNECTED":
            assert row["usable"] is True
            assert row["showConnected"] is True
            assert row["canProceed"] is True
        else:
            assert row["usable"] is False, state
            assert row["showConnected"] is False, state
            assert row["canProceed"] is False, state
    # Distinct, non-generic copy per state.
    labels = {row["label"] for row in rows}
    assert len(labels) == 5


def test_false_connected_negative_cases_never_render_as_connected() -> None:
    out = _run_node(
        _harness(
            "const cases = {"
            " disconnected: {state: 'CONNECTED', usable: true, expired: true},"
            " revokedFlag: {state: 'CONNECTED', usable: true, revoked: true},"
            " notUsable: {state: 'CONNECTED', usable: false},"
            " unknownState: {state: 'SOMETHING_ELSE', usable: true},"
            " missingState: {usable: true},"
            " notAnObject: 'CONNECTED',"
            " nullish: null"
            "};"
            "console.log(JSON.stringify(Object.keys(cases).map((k) => {"
            "  const m = H.deriveHandoffViewModel({conversationId: 'c1', requiresLocalAccess: true,"
            "   desktopInstalled: true, device: cases[k], handoff: {kind: 'deep_link', value: 'v'}});"
            "  return {case: k, state: m.device.state, usable: m.device.usable,"
            "   showConnected: m.showConnected, canProceed: m.canProceed};"
            "})));"
        )
    )
    rows = json.loads(out)
    assert len(rows) == 7
    for row in rows:
        assert row["showConnected"] is False, row
        assert row["canProceed"] is False, row
        assert row["usable"] is False, row
        assert row["state"] != "CONNECTED", row
    states = {row["case"]: row["state"] for row in rows}
    assert states["unknownState"] == "ACTION_REQUIRED"
    assert states["missingState"] == "ACTION_REQUIRED"
    assert states["revokedFlag"] == "REVOKED"
    assert states["notAnObject"] == "ACTION_REQUIRED"
    assert states["nullish"] == "ACTION_REQUIRED"


def test_update_required_variant_only_on_canonical_connected() -> None:
    out = _run_node(
        _harness(
            "console.log(JSON.stringify(["
            " H.normalizeDeviceProjection({state: 'CONNECTED', usable: true, variant: 'UPDATE_REQUIRED'}),"
            " H.normalizeDeviceProjection({state: 'OFFLINE', usable: false, variant: 'UPDATE_REQUIRED'}),"
            " H.normalizeDeviceProjection({state: 'CONNECTED', usable: true, variant: 'MADE_UP'})"
            "].map((d) => ({state: d.state, variant: d.variant}))));"
        )
    )
    rows = json.loads(out)
    assert rows[0] == {"state": "CONNECTED", "variant": "UPDATE_REQUIRED"}
    # An offline device must never be dressed up as merely needing an update.
    assert rows[1]["variant"] is None
    assert rows[2]["variant"] is None


# ---------------------------------------------------------------------------
# 6. Same conversation / run / task identity
# ---------------------------------------------------------------------------


def test_same_conversation_and_run_identity_is_preserved_through_handoff() -> None:
    out = _run_node(
        _harness(
            "const before = H.deriveHandoffViewModel(H.FIXTURES.installRequired);"
            "const after = H.deriveHandoffViewModel(H.FIXTURES.connectedComplete);"
            "console.log(JSON.stringify({"
            " before: before.identity, after: after.identity,"
            " mismatch: after.identityMismatch,"
            " hasIdentity: after.identity.hasIdentity}));"
        )
    )
    data = json.loads(out)
    assert data["before"] == data["after"]
    assert data["before"]["conversationId"] == "conv_fixture_3084_a"
    assert data["before"]["runId"] == "run_fixture_3084_a"
    assert data["before"]["taskId"] == "task_fixture_3084_a"
    assert data["mismatch"] is False
    assert data["hasIdentity"] is True


def test_handoff_claiming_a_different_conversation_is_flagged_not_accepted() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'conv_a', runId: 'run_a',"
            " taskId: 'task_a', requiresLocalAccess: true, desktopInstalled: true,"
            " device: {state: 'CONNECTED', usable: true},"
            " handoff: {kind: 'deep_link', value: 'v', conversationId: 'conv_b'}});"
            "console.log(JSON.stringify({mismatch: m.identityMismatch,"
            " conversationId: m.identity.conversationId, canProceed: m.canProceed}));"
        )
    )
    data = json.loads(out)
    assert data["mismatch"] is True
    # The live identity is never replaced by the handoff's claim.
    assert data["conversationId"] == "conv_a"


def test_identity_is_carried_onto_the_rendered_panel() -> None:
    out = _run_node(
        _harness(
            "const el = () => ({attrs: {}, textContent: '', hidden: false, disabled: false,"
            "  setAttribute(k, v) { this.attrs[k] = v; },"
            "  removeAttribute(k) { delete this.attrs[k]; }});"
            "const refs = {};"
            " ['panel','title','body','state','cta','installNote','openNote','identity',"
            "  'approval','approvalTitle','approvalBody','status','statusTitle','statusBody',"
            "  'result','resultTitle','resultBody','evidence','evidenceTitle','evidenceList']"
            "  .forEach((k) => { refs[k] = el(); });"
            "const m = H.deriveHandoffViewModel(H.FIXTURES.connectedComplete);"
            "H.projectHandoffPanel(refs, m, 'en');"
            "console.log(JSON.stringify({"
            " conversationId: refs.identity.attrs['data-conversation-id'],"
            " runId: refs.identity.attrs['data-run-id'],"
            " taskId: refs.identity.attrs['data-task-id'],"
            " state: refs.panel.attrs['data-claw-local-state'],"
            " usable: refs.panel.attrs['data-claw-local-usable'],"
            " contract: refs.panel.attrs['data-claw-local-contract']}));"
        )
    )
    data = json.loads(out)
    assert data["conversationId"] == "conv_fixture_3084_a"
    assert data["runId"] == "run_fixture_3084_a"
    assert data["taskId"] == "task_fixture_3084_a"
    assert data["state"] == "CONNECTED"
    assert data["usable"] == "true"
    assert data["contract"] == "b62-claw-local-handoff/1"


# ---------------------------------------------------------------------------
# 7. Approval / status / result / evidence projection
# ---------------------------------------------------------------------------


def test_approval_status_result_are_visible_when_upstream_declares_them() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.connectedComplete);"
            "console.log(JSON.stringify({"
            " approvalVisible: m.activity.approvalVisible, approvalState: m.activity.approvalState,"
            " statusVisible: m.activity.statusVisible, resultVisible: m.activity.resultVisible,"
            " evidenceVisible: m.activity.evidenceVisible, evidence: m.activity.evidence}));"
        )
    )
    data = json.loads(out)
    assert data["approvalVisible"] is True
    assert data["approvalState"] == "APPROVED"
    assert data["statusVisible"] is True
    assert data["resultVisible"] is True
    assert data["evidenceVisible"] is True
    assert data["evidence"] == [{"kind": "note", "text": "fixture evidence"}]


def test_pending_approval_is_visible_and_undecided() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.connected);"
            "console.log(JSON.stringify({visible: m.activity.approvalVisible,"
            " state: m.activity.approvalState, decided: m.activity.approvalDecided}));"
        )
    )
    data = json.loads(out)
    assert data == {"visible": True, "state": "PENDING", "decided": False}


def test_activity_blocks_stay_hidden_when_nothing_was_declared() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel(H.FIXTURES.connected);"
            "console.log(JSON.stringify({resultVisible: m.activity.resultVisible,"
            " evidenceVisible: m.activity.evidenceVisible}));"
        )
    )
    data = json.loads(out)
    assert data["resultVisible"] is False
    assert data["evidenceVisible"] is False


def test_evidence_drops_any_item_carrying_raw_process_material() -> None:
    out = _run_node(
        _harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'c1', requiresLocalAccess: true,"
            "  device: {state: 'CONNECTED', usable: true},"
            "  evidence: [{kind: 'note', text: 'safe'},"
            "   {kind: 'stdout', text: 'leak'},"
            "   {kind: 'note', text: 'x', argv: ['ls']},"
            "   {kind: 'note', text: 'y', pairingToken: 'zzz'}]});"
            "console.log(JSON.stringify(m.activity.evidence));"
        )
    )
    assert json.loads(out) == [{"kind": "note", "text": "safe"}]


# ---------------------------------------------------------------------------
# 8. CTA transition
# ---------------------------------------------------------------------------


def test_cta_is_disabled_until_the_projection_is_genuinely_proceedable() -> None:
    out = _run_node(
        _harness(
            "const el = () => ({attrs: {}, textContent: '', hidden: false, disabled: false,"
            "  setAttribute(k, v) { this.attrs[k] = v; },"
            "  removeAttribute(k) { delete this.attrs[k]; }});"
            "const refs = {};"
            " ['panel','title','body','state','cta','installNote','openNote','identity',"
            "  'approval','approvalTitle','approvalBody','status','statusTitle','statusBody',"
            "  'result','resultTitle','resultBody','evidence','evidenceTitle','evidenceList']"
            "  .forEach((k) => { refs[k] = el(); });"
            "const out = ['installRequired', 'installedPairing', 'connected'].map((name) => {"
            "  const m = H.deriveHandoffViewModel(H.FIXTURES[name]);"
            "  H.projectHandoffPanel(refs, m, 'ko');"
            "  return {name, canProceed: m.canProceed, ctaDisabled: refs.cta.disabled,"
            "   ariaDisabled: refs.cta.attrs['aria-disabled'] || null,"
            "   ctaText: refs.cta.textContent, handoffAvailable: refs.cta.attrs['data-handoff-available']};"
            "});"
            "console.log(JSON.stringify(out));"
        )
    )
    rows = json.loads(out)
    by_name = {row["name"]: row for row in rows}
    assert by_name["installRequired"]["ctaDisabled"] is True
    assert by_name["installedPairing"]["ctaDisabled"] is True
    assert by_name["connected"]["ctaDisabled"] is False
    assert by_name["connected"]["handoffAvailable"] == "true"
    assert by_name["connected"]["ctaText"] == "이 컴퓨터 연결 열기"


def test_panel_is_hidden_when_no_local_access_is_required() -> None:
    out = _run_node(
        _harness(
            "const el = () => ({attrs: {}, textContent: '', hidden: false, disabled: false,"
            "  setAttribute(k, v) { this.attrs[k] = v; },"
            "  removeAttribute(k) { delete this.attrs[k]; }});"
            "const refs = {panel: el()};"
            "const m = H.deriveHandoffViewModel({conversationId: 'c1'});"
            "H.projectHandoffPanel(refs, m, 'ko');"
            "console.log(JSON.stringify({hidden: refs.panel.hidden}));"
        )
    )
    assert json.loads(out)["hidden"] is True


def test_cta_is_a_real_button_with_explicit_type() -> None:
    out = _run_node(
        _harness(
            "const el = () => ({attrs: {}, textContent: '', hidden: false, disabled: false,"
            "  setAttribute(k, v) { this.attrs[k] = v; },"
            "  removeAttribute(k) { delete this.attrs[k]; }});"
            "const refs = {panel: el(), cta: el()};"
            "H.projectHandoffPanel(refs, H.deriveHandoffViewModel(H.FIXTURES.connected), 'ko');"
            "console.log(JSON.stringify({type: refs.cta.attrs.type}));"
        )
    )
    assert json.loads(out)["type"] == "button"


# ---------------------------------------------------------------------------
# 9. Copy: no developer runtime jargon
# ---------------------------------------------------------------------------


def test_consumer_copy_never_exposes_developer_runtime_jargon() -> None:
    out = _run_node(
        _harness(
            "const banned = ['agent runtime', 'mcp', 'broker', 'websocket', 'execution target',"
            " 'sandbox', 'process', 'capability manifest', 'pairing token', 'deep link'];"
            "const hits = [];"
            "['ko', 'en'].forEach((lang) => {"
            "  Object.entries(H.copy(lang)).forEach(([key, value]) => {"
            "    const lower = String(value).toLowerCase();"
            "    banned.forEach((term) => { if (lower.includes(term)) hits.push(lang + ':' + key + ':' + term); });"
            "  });"
            "});"
            "console.log(JSON.stringify(hits));"
        )
    )
    assert json.loads(out) == []


def test_both_locales_define_the_same_copy_keys() -> None:
    out = _run_node(
        _harness(
            "const ko = Object.keys(H.copy('ko')).sort();"
            "const en = Object.keys(H.copy('en')).sort();"
            "console.log(JSON.stringify({ko, en, same: JSON.stringify(ko) === JSON.stringify(en)}));"
        )
    )
    data = json.loads(out)
    assert data["same"] is True
    assert "claw-local-cta-connect" in data["ko"]
    assert "claw-local-panel-aria" in data["en"]


def test_korean_cta_matches_the_product_wording() -> None:
    out = _run_node(
        _harness("console.log(H.copy('ko')['claw-local-cta-connect']);")
    )
    assert out == "이 컴퓨터 연결"


def test_locale_dictionary_declares_the_module_keys_in_both_languages() -> None:
    source = _locale_source()
    for key in (
        "claw-local-title",
        "claw-local-body",
        "claw-local-cta-connect",
        "claw-local-cta-install",
        "claw-local-state-connected",
        "claw-local-state-offline",
        "claw-local-approval-title",
        "claw-local-status-title",
        "claw-local-result-title",
        "claw-local-evidence-title",
        "claw-local-panel-aria",
    ):
        assert source.count(f'"{key}"') == 2, f"{key} must exist once in ko and once in en"


# ---------------------------------------------------------------------------
# 10. Korean IME regression protection
# ---------------------------------------------------------------------------


def test_enter_during_ime_composition_does_not_submit() -> None:
    out = _run_node(
        _harness(
            "const guard = H.createCompositionGuard();"
            "const cases = {"
            " isComposing: {key: 'Enter', isComposing: true},"
            " legacy229: {key: 'Enter', keyCode: 229},"
            " tracked: null,"
            " plain: {key: 'Enter'},"
            " shift: {key: 'Enter', shiftKey: true},"
            " other: {key: 'a'},"
            " ctrl: {key: 'Enter', ctrlKey: true}"
            "};"
            "guard.start();"
            "cases.tracked = {key: 'Enter'};"
            "console.log(JSON.stringify({"
            " isComposing: H.shouldSubmitOnEnter(cases.isComposing),"
            " legacy229: H.shouldSubmitOnEnter(cases.legacy229),"
            " tracked: H.shouldSubmitOnEnter(cases.tracked, guard),"
            " plain: H.shouldSubmitOnEnter(cases.plain),"
            " shift: H.shouldSubmitOnEnter(cases.shift),"
            " other: H.shouldSubmitOnEnter(cases.other),"
            " ctrl: H.shouldSubmitOnEnter(cases.ctrl),"
            " nullish: H.shouldSubmitOnEnter(null)}));"
            "guard.end();"
        )
    )
    data = json.loads(out)
    # Composition must never submit.
    assert data["isComposing"] is False
    assert data["legacy229"] is False
    # The tracker alone (engine that omits event.isComposing) must also block.
    assert data["tracked"] is False
    # After composition ends, a genuine Enter submits again.
    assert _run_node(
        _harness(
            "const g = H.createCompositionGuard();"
            "g.start(); g.end();"
            "console.log(String(H.shouldSubmitOnEnter({key: 'Enter'}, g)));"
        )
    ) == "true"
    # A genuine Enter does submit.
    assert data["plain"] is True
    # Shift+Enter, other keys, chords and junk must not submit.
    assert data["shift"] is False
    assert data["other"] is False
    assert data["ctrl"] is False
    assert data["nullish"] is False


def test_composition_guard_tracks_the_full_composition_lifecycle() -> None:
    out = _run_node(
        _harness(
            "const g = H.createCompositionGuard();"
            "const seq = [];"
            "seq.push(g.isComposing());"
            "g.start(); seq.push(g.isComposing());"
            "g.update(); seq.push(g.isComposing());"
            "g.end(); seq.push(g.isComposing());"
            "g.start(); g.reset(); seq.push(g.isComposing());"
            "console.log(JSON.stringify(seq));"
        )
    )
    assert json.loads(out) == [False, True, True, False, False]


def test_composer_uses_the_shared_ime_guard() -> None:
    app = _app_source()
    assert "PadiemClawLocalHandoff" in app
    assert "shouldSubmitOnEnter" in app
    assert "createCompositionGuard" in app
    for event_name in ("compositionstart", "compositionupdate", "compositionend"):
        assert f'"{event_name}"' in app, f"{event_name} listener missing"
    # The old unguarded submit path must be gone.
    assert 'if (event.key === "Enter" && !event.shiftKey) {' not in app


# ---------------------------------------------------------------------------
# 11. app.js integration and non-authority at the integration layer
# ---------------------------------------------------------------------------


def test_app_exposes_a_narrow_injection_seam_with_no_transport() -> None:
    app = _app_source()
    assert "window.__padiemClawLocalHandoff" in app
    assert "projectLocalHandoff" in app
    assert "padiem:claw-local-connect-requested" in app
    # The CTA must not navigate, open a deep link, or hit the network itself.
    assert "window.location" not in app.split("#3084 — Claw")[1] if "#3084 — Claw" in app else True
    for forbidden in (
        "new WebSocket",
        "EventSource",
        "crypto.subtle",
        "localStorage",
        "sessionStorage",
    ):
        assert forbidden not in app, f"{forbidden} must not be introduced by #3084"


def test_app_cta_handler_refuses_when_the_projection_is_not_proceedable() -> None:
    app = _app_source()
    assert "if (!model || !model.canProceed) return;" in app


def test_app_reprojects_on_locale_change() -> None:
    app = _app_source()
    assert 'window.addEventListener("padiem:localechange"' in app


# ---------------------------------------------------------------------------
# 12. Markup + asset wiring
# ---------------------------------------------------------------------------


def test_index_declares_the_handoff_panel_with_required_ids() -> None:
    html = _index_source()
    assert '<link rel="stylesheet" href="./claw-local-handoff.css" />' in html
    assert '<script src="./claw-local-handoff.js"></script>' in html
    for element_id in (
        "clawLocalHandoff",
        "clawLocalTitle",
        "clawLocalBody",
        "clawLocalState",
        "clawLocalCta",
        "clawLocalIdentity",
        "clawLocalApproval",
        "clawLocalStatus",
        "clawLocalResult",
        "clawLocalEvidence",
    ):
        assert f'id="{element_id}"' in html, element_id


def test_index_uses_semantic_button_for_the_cta() -> None:
    html = _index_source()
    match = re.search(r'<button[^>]*id="clawLocalCta"[^>]*>', html)
    assert match, "CTA must be a <button>"
    tag = match.group(0)
    assert 'type="button"' in tag
    assert "<a" not in tag


def test_handoff_script_loads_before_app_js() -> None:
    html = _index_source()
    assert html.index('src="./claw-local-handoff.js"') < html.index('src="./app.js"')


def test_static_locale_bindings_only_reference_declared_keys() -> None:
    locale_source = _locale_source()
    start = locale_source.index("ko: {")
    end = locale_source.index("en: {", start)
    keys = set(re.findall(r'"([^"]+)":', locale_source[start:end]))
    referenced = set(
        re.findall(r'data-locale-(?:key|aria-label)="([^"]+)"', _index_source())
    )
    assert referenced
    assert referenced <= keys, referenced - keys


# ---------------------------------------------------------------------------
# 13. Accessibility
# ---------------------------------------------------------------------------


def test_panel_carries_an_accessible_label_and_live_region() -> None:
    html = _index_source()
    assert 'aria-label="컴퓨터 연결 안내"' in html
    assert 'id="clawLocalState"' in html
    css = MODULE_CSS.read_text(encoding="utf-8")
    assert 'aria-live' in css or "aria-live" in html


def test_css_keeps_a_visible_focus_ring() -> None:
    css = MODULE_CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline:" in css
    # Focus styling must never be removed without a replacement.
    assert "outline: none" not in css
    assert "outline:0" not in css


def test_css_covers_the_390px_mobile_class_layout() -> None:
    css = MODULE_CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 430px)" in css
    block = css.split("@media (max-width: 430px)")[1]
    assert "flex-direction: column" in block
    assert "width: 100%" in block


def test_css_honours_reduced_motion() -> None:
    css = MODULE_CSS.read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "transition: none" in css


# ---------------------------------------------------------------------------
# 14. No second authority, no production mutation
# ---------------------------------------------------------------------------


# The exact /api/* endpoint set that existed in static/app.js at the #3084 base
# commit (4b939347accc5bb45701fd4f31cd588f30258c6d). Pinned as a literal on
# purpose: CI checks out a shallow clone, so the base blob is not available to
# `git show` from inside the test. #3084 must not add to this set.
BASE_APP_ENDPOINTS = frozenset(
    {
        "/api/auth/logout",
        "/api/auth/password/login",
        "/api/auth/password/register",
        "/api/auth/status",
        "/api/claw/approvals/decision",
        "/api/claw/manual-intake/execute",
        "/api/claw/manual-intake/preview",
        "/api/claw/memory",
        "/api/claw/memory/approve",
        "/api/claw/memory/reject",
        "/api/claw/runs?limit=10",
        "/api/conversations",
        "/api/projects",
    }
)


def test_no_new_backend_route_or_worker_endpoint_is_introduced() -> None:
    """#3084 is a Web slice. It must not add a server endpoint of its own."""
    assert "/api/" not in _source()

    present = set(re.findall(r'"/api/[^"]+"', _app_source()))
    # The regex captures the surrounding quotes; the pinned baseline does not.
    present = {value.strip('"') for value in present}
    added = present - BASE_APP_ENDPOINTS
    assert not added, f"#3084 introduced new endpoints: {sorted(added)}"
    # The pre-existing surface is untouched: nothing dropped either.
    assert present == BASE_APP_ENDPOINTS


def test_no_deploy_or_environment_mutation_in_the_change() -> None:
    """No production mutation: the slice adds only static UI plus a test.

    Asserted on the working tree rather than on a `git diff` against the base
    commit, because CI's shallow clone cannot resolve the base blob.
    """
    # The #3084 module and its stylesheet are static assets only.
    assert _source().lstrip().startswith("//")
    assert ".wrangler" not in _source()
    assert "wrangler.toml" not in _source()

    # No production deploy/mutation switch is introduced anywhere in the slice.
    for path in (MODULE_PATH, MODULE_CSS, APP_PATH, INDEX_PATH):
        text = path.read_text(encoding="utf-8")
        for marker in ("PRODUCTION_DEPLOY", "PRODUCTION_MUTATION", "wrangler deploy"):
            assert marker not in text, f"{path.name} introduced {marker}"

    # The CI workflow change is limited to the JS syntax check for the new
    # module. This file already contained one `wrangler deploy` step before
    # #3084, so the assertion is that #3084 added no *second* one rather than
    # that none exists.
    workflow = (ROOT.parent.parent / ".github" / "workflows" / "b62-padiem-chat-ci.yml").read_text(
        encoding="utf-8"
    )
    assert "node --check static/claw-local-handoff.js" in workflow
    assert workflow.count("wrangler deploy") == 1, "a deploy step was added or removed"
    out = _run_node(
        _harness(
            "const a = H.deriveHandoffViewModel(H.FIXTURES.connected);"
            "const b = H.deriveHandoffViewModel(H.FIXTURES.connected);"
            "console.log(JSON.stringify({"
            " stable: JSON.stringify(a) === JSON.stringify(b),"
            " handoffValue: a.handoff.value}));"
        )
    )
    data = json.loads(out)
    assert data["stable"] is True
    assert "fixture" in data["handoffValue"]
