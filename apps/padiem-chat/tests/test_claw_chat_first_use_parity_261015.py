"""Owner-approved Chat/Claw one composer / card frame boundary."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CAP = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
FOCUS = (STATIC / "claw-focus-layout.css").read_text(encoding="utf-8")
CHIPS = (STATIC / "claw-connection-chips.js").read_text(encoding="utf-8")


def test_one_canonical_composer_and_tier_control_for_chat_and_claw():
    assert HTML.count('id="composerForm"') == 1
    assert HTML.count('id="messageInput"') == 1
    assert HTML.count('class="model-pill composer-tier-trigger"') == 1
    assert 'optionalModels.appendChild(exactModelControl)' in CAP
    assert 'modePanel.appendChild(optionalModels)' in CAP
    assert 'manual.value=select.value' in (STATIC / "claw-verified-model-choice.js").read_text(encoding="utf-8")
    assert 'contextSnapshot.selectedModelId' in APP


def test_claw_dedicated_connectors_keep_real_buttons_inside_chat_card_geometry():
    for val in ("computer", "drive", "github", "web"):
        assert f'data-claw-card="{val}"' in HTML
    assert 'CENTRAL_CLAW_CHAT_FIRST_USE_PARITY_20261015' in CSS
    # Chat first-use cells and the Claw connector cards are the SAME surface, so
    # the grid row must resolve to one height in both modes. The row floor is the
    # tallest label and the shorter Claw labels keep the slack as whitespace
    # instead of shrinking the card (main measured 145px vs 116px).
    assert 'grid-auto-rows: minmax(145px, auto);' in CSS
    # The card is a positioning wrapper only: the inner .starter carries the Chat
    # box and paint, so Claw no longer stacks a second card surface on top of it.
    assert '.claw-home-card > .claw-workspace-starter' in FOCUS
    assert 'background: none !important;' in FOCUS
    assert '.claw-home-card > .claw-card-status' in FOCUS
    # Truthful connection headline in the top-right of every connector card.
    for status_id in ("clawPcCardStatus", "clawDriveCardStatus", "clawGithubCardStatus"):
        assert f'id="{status_id}"' in HTML
    assert 'claw-card-status' in HTML
    # Bottom-right carries the ON/OFF switch alone: the inline label is removed
    # and the switch is taken out of flow so it cannot stretch the card.
    assert '.claw-home-card .claw-connection-label' in FOCUS
    assert '.claw-home-card > .claw-connection-toggle' in FOCUS
    assert 'bottom: 12px;' in FOCUS
    assert 'position: absolute;' in FOCUS
    # Drive and GitHub drive the same headline; no inline "확인 불가" row remains.
    assert 'clawDriveCardStatus' in CHIPS
    assert 'clawGithubCardStatus' in CHIPS
    for label in ('class="claw-connection-label" hidden',):
        assert HTML.count(label) == 3


def test_approved_memory_stays_out_of_first_screen_without_deleting_owner_data():
    assert 'const onLanding = clawWorkspace?.dataset.view === "general"' in APP
    assert '&& !onLanding;' in APP
    assert 'loadApprovedMemoryList()' in APP
    assert 'id="clawApprovedMemory"' in HTML
