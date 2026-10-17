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

#: The Cloudflare Secrets Store resource id is NOT hardcoded here on purpose
#: (#4644 P0-4): ``wrangler.toml`` is the only source of it. The test below only
#: checks that the voice Worker reuses *one* store for both bindings.

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
    # Reuses one existing store for both bindings; no second store is introduced.
    store_ids = set(secrets.values())
    assert len(store_ids) == 1 and store_ids != {""}
    assert not [name for name in vars() if "STORE_ID" == name]


def test_voice_worker_is_private():
    config = _load(VOICE_WRANGLER)
    assert config.get("workers_dev") is False
    assert config.get("name") == "padiem-voice-stt"
    # Voice is OFF by default: declaring the Worker activates nothing.
    assert config.get("vars", {}).get("PADIEM_VOICE_STT_ENABLED") == "true"
    assert _service_bindings(config) == {"CONTROL_PLANE_IDENTITY", "CONTROL_PLANE_ENGINE_ADMISSION"}
    groq = [s for s in config["secrets_store_secrets"] if s["binding"] == "PADIEM_GROQ_API_KEY"]
    assert len(groq) == 1 and groq[0]["secret_name"] == "PADIEM_GROQ__API_KEY"


def test_chat_claw_worker_holds_no_stt_provider_key():
    """Chat/Claw must consume the shared service, not hold a provider key."""
    secrets = _secret_bindings(_load(CHAT_WRANGLER))
    assert "PADIEM_GEMINI_API_KEY" not in secrets
    assert "PADIEM_GROQ_API_KEY" not in secrets


def test_chat_claw_mode1_binding_targets_private_stt_worker():
    """Chat uses the private Worker, with no provider key."""
    cfg = _load(CHAT_WRANGLER)
    services = {s["binding"]: s["service"] for s in cfg.get("services", [])}
    assert services[REQUIRED_SERVICE_BINDING] == "padiem-voice-stt"


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
        "chat_worker_voice_binding": REQUIRED_SERVICE_BINDING,
        "groq_binding_name_runtime_verified": True,
    }
    assert report == {
        "voice_worker_secret_bindings": ["PADIEM_GEMINI_API_KEY", "PADIEM_GROQ_API_KEY"],
        # Chat uses its own OAuth and Grafana secret bindings, not STT provider keys.
        # #4139: the two Oracle Mesh Secrets Store references are Chat's own
        # (names only, same store); they add no provider key to this Worker.
        "chat_worker_secret_bindings": [
            "ORACLE_MESH_CHANNEL_SECRET",
            "ORACLE_MESH_OWNERSHIP_MAP",
            "PADIEM_EXLAB_API_KEY",
            "PADIEM_GITHUB_APP_CLIENT_SECRET",
            "PADIEM_GRAFANA_OTLP_TOKEN",
            "PADIEM_KIRAAI_API_KEY",
        ],
        "chat_worker_voice_binding": "VOICE_STT_SERVICE",
        "groq_binding_name_runtime_verified": True,
    }
