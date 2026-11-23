"""Owner-approved Chat/Claw one composer / card frame boundary."""
# #8060: shipped reads live in _support; the markup and CSS checks stay.
from _support import claw_chat_first_use_source as sheets

HTML = sheets.sheet("index.html")
CAP = sheets.sheet("product-capabilities.js")
APP = sheets.sheet("app.js")
CSS = sheets.sheet("shared-six-panel-frame.css")
FOCUS = sheets.sheet("claw-focus-layout.css")
CHIPS = sheets.sheet("claw-connection-chips.js")


def test_one_canonical_composer_and_tier_control_for_chat_and_claw():
    assert HTML.count('id="composerForm"') == 1
    assert HTML.count('id="messageInput"') == 1
    assert HTML.count('class="model-pill composer-tier-trigger"') == 1
    assert 'exactModelControl' not in CAP
    assert 'modePanel.appendChild(modePanel)' not in CAP
    assert 'id="clawVerifiedModelSelect"' not in HTML
    assert 'id="clawModelIdInput"' not in HTML
    assert 'payload.model_id = contextSnapshot.selectedModelId' not in APP


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
    memory_mod = sheets.sheet("chat-memory-module.js")
    assert 'const onLanding = deps.clawWorkspace?.dataset.view === "general"' in memory_mod
    assert '&& !onLanding;' in memory_mod
    assert 'loadApprovedMemoryList()' in memory_mod
    assert 'app.syncApprovedMemoryVisibility()' in APP
    assert 'id="clawApprovedMemory"' in HTML
