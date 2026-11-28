"""Connector pages — the grid keeps one line per connector; a tile opens its
own page and the existing card is MOVED there, never rebuilt.

The move is what keeps this truthful: the card's listeners, endpoints, status
writers and the single device-directory reader all ride along unchanged, and
the dedicated page adds only routing and layout.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# #8060: shipped reads live in _support; the markup and CSS checks stay here.
from _support import connector_pages_source as sheets

HTML = sheets.html()
PAGES = sheets.pages()
CSS = sheets.css()


def test_the_detail_shell_and_grid_ids_ship_with_the_page():
    assert 'id="connectorsGrid"' in HTML
    for anchor in ('id="connectorDetail"', 'id="connectorDetailBack"',
                   'id="connectorDetailTitle"', 'id="connectorDetailStatus"',
                   'id="connectorDetailBody"', 'id="connectorDetailConnect"'):
        assert anchor in HTML
    assert '<script src="./connector-pages.js" defer></script>' in HTML
    assert 'href="./connector-pages.css"' in HTML


def test_the_module_moves_the_card_instead_of_rebuilding_it():
    assert "window.PadiemConnectorPages" in PAGES
    assert "body.appendChild(card)" in PAGES
    assert "home.parent.insertBefore(card, home.next)" in PAGES
    # No connector endpoint or connection authority is introduced here.
    assert "/api/" not in PAGES


def test_the_tile_speaks_only_the_shared_four_state_vocabulary():
    # The card's dataset is the state owner; the tile maps it to the shared
    # constant and never copies a raw server sentence (no “워크스페이스”).
    assert 'card.dataset.connectorStatus' in PAGES
    assert 'return "곧 지원돼요"' in PAGES
    assert "워크스페이스" not in PAGES
    for state in ('"connected"', '"not_connected"', '"connecting"', '"failed"'):
        assert state in PAGES


def test_only_active_pcs_count_as_connected_and_paused_are_named():
    assert 'pc-pairing-state[data-state="active"]' in PAGES
    assert '"대 멈춤"' in PAGES
    # Zero connected rows fall back to the shared disconnected word.
    assert "const text = statusText(card);" in PAGES


def test_the_computer_page_folds_the_card_head_and_offers_a_small_retry():
    assert ".connector-detail-body .capability-card > strong" in CSS
    assert ".connector-detail-body #clawComputerDeviceStatusButton" in CSS
    assert "connectorDetailRetry" in PAGES
    assert 'link.textContent = "다시 확인"' in PAGES
    assert ('content: "%s"' % chr(0x25B8)) in CSS and ('content: "%s"' % chr(0x25BE)) in CSS


def test_the_tile_keeps_one_line_and_the_page_owns_the_full_card():
    assert "#connectorsGrid .capability-card.connector-tile > .capability-workspace" in CSS
    assert "#connectorsGrid .capability-card.connector-tile #pcPairingSection" in CSS
    # The dedicated page hides the card's duplicate heading/CTA, not the card.
    assert ".connector-detail-body .pc-pairing > .pc-pairing-connect" in CSS
    assert ".connector-detail-body .capability-card {\n  width: 100%;\n}" in CSS


def test_the_computer_page_owns_the_one_connect_action_and_folds_advanced():
    assert 'id="connectorDetailConnect"' in HTML
    assert "PadiemPcConnectFlow" in PAGES
    assert "고급 설정" in PAGES
    assert "pc-connector-advanced" in PAGES and "pc-connector-advanced" in CSS


def test_unverified_telegram_slack_copy_is_preparing_but_other_failure_is_not() -> None:
    """Execute the shipped tile projection (not a guessed screenshot).

    The trusted-projection reason remains unverified in the server row; only
    a neutral copy hint changes the tile. Any other unverified reason must
    retain the existing failed-check line. Both locale strings come from the
    existing workspace key; no new colour or visual class is introduced.
    """
    node = shutil.which("node")
    assert node, "Node.js is required for the connector tile contract"
    script = r"""
const fs = require("node:fs"), vm = require("node:vm");
const on = {};
const cards = [];
function card(name, display) {
  let tile = null;
  const label = { textContent:name, after(el) { tile=el; } };
  const o = {
    dataset:{connectorStatus:"unverified",connector:name},
    classList:{contains(){return false;},add(){}},
    querySelector(selector) {
      if (selector === ".capability-soon") return null;
      if (selector === ".connector-tile-status") return tile;
      if (selector === "strong") return label;
      if (selector === "[data-connector-workspace]") return {textContent:"준비 중"};
      return null;
    },
    appendChild(el) {tile=el;}, setAttribute(){}, getAttribute(){return null;},
    status() {return tile?.textContent || "";}
  };
  if (display) o.dataset.connectorDisplay = display;
  cards.push(o);
  return o;
}
card("telegram","unverified");
card("slack","unverified");
card("google-drive",null);
const grid = {querySelectorAll(sel) {return sel === ".capability-card" ? cards : []}};
const view = {hidden:true};
global.window=globalThis;
global.document = {
  readyState:"loading",documentElement:{lang:"ko"},
  addEventListener(name,fn) {on[name]=fn;},
  getElementById(id) {return id==="connectorsGrid" ? grid : id==="connectorsView" ? view : null;},
  createElement() {return {className:"",textContent:"",setAttribute(){}};},
};
global.location={hash:"#connectors"};
window.addEventListener=()=>{};
window.PadiemConnectorVocabulary={status(state){
  const en=document.documentElement.lang==="en";
  return state==="failed" ? (en?"Check failed · Try again":"확인 실패 · 다시 시도") : state;
}};
window.__padiemLocale={text(key){
  if (key!=="connectors-workspace-unverified") return key;
  return document.documentElement.lang==="en"?"Coming soon":"준비 중";
}};
global.MutationObserver=class {observe(){}};
vm.runInThisContext(fs.readFileSync(process.argv[1],"utf8"),{filename:"connector-pages.js"});
on.DOMContentLoaded();
const ko=cards.map(c=>c.status());
document.documentElement.lang="en";
on.DOMContentLoaded();
const en=cards.map(c=>c.status());
console.log(JSON.stringify({ko,en}));
"""
    path = Path(__file__).resolve().parents[1] / "static" / "connector-pages.js"
    result = subprocess.run([node, "-e", script, str(path)], check=True,
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=15)
    evidence = json.loads(result.stdout.strip())
    assert evidence["ko"] == ["준비 중", "준비 중", "확인 실패 · 다시 시도"]
    assert evidence["en"] == ["Coming soon", "Coming soon", "Check failed · Try again"]
