"""Per-product server permission / Secret binding-name verification (#4643).

The task boundary is explicit: verify **names and presence only**. No key value
is read, printed, compared or stored — the values stay inside the Cloudflare
Secrets Store and are never present in this repository at all.

This test both asserts the current state and produces the machine-readable
report the completion handoff quotes, so a later activation slice cannot silently
change which binding a product is expected to hold.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

VOICE_WRANGLER = REPO_ROOT / "apps" / "padiem-voice-stt" / "wrangler.toml"
CHAT_WRANGLER = REPO_ROOT / "apps" / "padiem-chat" / "wrangler.toml"
B66_BRIDGE = REPO_ROOT / "reference" / "business-66-padiem-quote-v1" / "_worker.js"

EXPECTED_STORE_ID = "f0b09ca04a7b43248154c773704a5616"

#: The Service Binding each product must gain before it can reach the shared
#: voice Worker. Declared here as the required name; it is deliberately NOT
#: added to a product config in this slice because the voice Worker is not
#: deployed yet (adding it would break that product's deploy).
REQUIRED_SERVICE_BINDING = "VOICE_STT_SERVICE"


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _secret_bindings(config: dict) -> dict[str, str]:
    """Return ``{binding_name: store_id}`` for every Secrets Store binding."""
    found: dict[str, str] = {}
    for entry in config.get("secrets_store_secrets", []) or []:
        name = entry.get("binding")
        if isinstance(name, str):
            found[name] = str(entry.get("store_id", ""))
    return found


def _service_bindings(config: dict) -> set[str]:
    return {
        entry["binding"]
        for entry in (config.get("services", []) or [])
        if isinstance(entry.get("binding"), str)
    }


def test_voice_worker_declares_both_provider_secret_bindings():
    secrets = _secret_bindings(_load(VOICE_WRANGLER))
    assert set(secrets) == {"PADIEM_GEMINI_API_KEY", "PADIEM_GROQ_API_KEY"}
    # Reuses the existing store; no new store is introduced.
    assert set(secrets.values()) == {EXPECTED_STORE_ID}


def test_voice_worker_is_private():
    config = _load(VOICE_WRANGLER)
    assert config.get("workers_dev") is False
    assert config.get("name") == "padiem-voice-stt"
    # Voice is OFF by default: declaring the Worker activates nothing.
    assert config.get("vars", {}).get("PADIEM_VOICE_STT_ENABLED") == "false"


def test_chat_claw_worker_holds_no_stt_provider_key():
    """Chat/Claw must consume the shared service, not hold a provider key."""
    secrets = _secret_bindings(_load(CHAT_WRANGLER))
    assert "PADIEM_GEMINI_API_KEY" not in secrets
    assert "PADIEM_GROQ_API_KEY" not in secrets


def test_chat_claw_service_binding_is_still_missing():
    """The one remaining Chat/Claw server prerequisite, reported as a name."""
    services = _service_bindings(_load(CHAT_WRANGLER))
    assert REQUIRED_SERVICE_BINDING not in services


def test_b66_bridge_holds_no_secret_and_targets_the_chat_origin():
    text = B66_BRIDGE.read_text(encoding="utf-8")
    assert "PADIEM_GEMINI_API_KEY" not in text
    assert "PADIEM_GROQ_API_KEY" not in text
    assert "chat.padiem.net" in text


def test_binding_report_matches_expected_state():
    voice = _secret_bindings(_load(VOICE_WRANGLER))
    chat = _secret_bindings(_load(CHAT_WRANGLER))
    report = {
        "voice_worker_secret_bindings": sorted(voice),
        "chat_worker_secret_bindings": sorted(chat),
        "chat_worker_missing_service_binding": REQUIRED_SERVICE_BINDING,
        "groq_binding_name_runtime_verified": False,
    }
    assert report == {
        "voice_worker_secret_bindings": ["PADIEM_GEMINI_API_KEY", "PADIEM_GROQ_API_KEY"],
        "chat_worker_secret_bindings": ["PADIEM_EXLAB_API_KEY", "PADIEM_KIRAAI_API_KEY"],
        "chat_worker_missing_service_binding": "VOICE_STT_SERVICE",
        "groq_binding_name_runtime_verified": False,
    }
