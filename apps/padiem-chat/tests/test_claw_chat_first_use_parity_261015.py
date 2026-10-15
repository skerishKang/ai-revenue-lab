"""Owner-approved Chat/Claw one composer / card frame boundary."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CAP = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
CSS = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")


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
    assert 'height: 116px;' in CSS
    assert 'height: 26px !important;' in CSS
    assert 'claw-connection-toggle' in CSS
    assert 'CENTRAL_CLAW_CHAT_FIRST_USE_PARITY_20261015' in CSS


def test_approved_memory_stays_out_of_first_screen_without_deleting_owner_data():
    assert 'const onLanding = clawWorkspace?.dataset.view === "general"' in APP
    assert '&& !onLanding;' in APP
    assert 'loadApprovedMemoryList()' in APP
    assert 'id="clawApprovedMemory"' in HTML
