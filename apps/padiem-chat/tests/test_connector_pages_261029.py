"""Connector pages — the grid keeps one line per connector; a tile opens its
own page and the existing card is MOVED there, never rebuilt.

The move is what keeps this truthful: the card's listeners, endpoints, status
writers and the single device-directory reader all ride along unchanged, and
the dedicated page adds only routing and layout.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
HTML = (BASE / "index.html").read_text(encoding="utf-8")
PAGES = (BASE / "connector-pages.js").read_text(encoding="utf-8")
CSS = (BASE / "connector-pages.css").read_text(encoding="utf-8")


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


def test_the_tile_reads_the_one_status_owner():
    # Live writer first, server workspace state second, capability line last.
    order = PAGES.index("#clawComputerLiveStatus")
    assert order < PAGES.index("[data-connector-workspace]") < PAGES.index(".capability-read")


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
