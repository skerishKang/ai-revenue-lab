"""#3523: exact approved Charliekant Secrets Store binding metadata.

No secret values; only fixed, publicly non-sensitive binding identities.
Never allow unrelated additions or drift in an additive new-main deploy.
"""
from __future__ import annotations

WEB_SECRET_STORE_ID = "f0b09ca04a7b43248154c773704a5616"
WEB_SECRET_NAMES = {
    "TINYFISH_API_KEY": "PADIEM_TINY_FISH_API_KEY",
    "PADIEM_CHAT_DAUM_REST_API_KEY": "PADIEM_KAKAO_API_KEY",
}


def expected_web_secret_bindings() -> dict[str, dict[str, str]]:
    return {
        name: {
            "type": "secrets_store_secret",
            "name": name,
            "store_id": WEB_SECRET_STORE_ID,
            "secret_name": secret_name,
        }
        for name, secret_name in WEB_SECRET_NAMES.items()
    }


# #4139: the two Oracle Mesh Secrets Store identities, same account store as the
# web secrets. Declared in wrangler.toml; attached to live bindings only by the
# explicit Oracle attach mode. Never carries values.
ORACLE_MESH_SECRET_NAMES = ("ORACLE_MESH_CHANNEL_SECRET", "ORACLE_MESH_OWNERSHIP_MAP")


def expected_oracle_mesh_bindings() -> dict[str, dict[str, str]]:
    return {
        name: {
            "type": "secrets_store_secret",
            "name": name,
            "store_id": WEB_SECRET_STORE_ID,
            "secret_name": name,
        }
        for name in ORACLE_MESH_SECRET_NAMES
    }


# #4139: one shared Engine -> Chat desktop proof identity. Engine and Chat
# reference the same store object; the value is never read by a deploy.
CLAW_DESKTOP_SECRET_NAME = "CLAW_ENGINE_DESKTOP_SECRET"


def expected_claw_desktop_bindings() -> dict[str, dict[str, str]]:
    return {
        CLAW_DESKTOP_SECRET_NAME: {
            "type": "secrets_store_secret",
            "name": CLAW_DESKTOP_SECRET_NAME,
            "store_id": WEB_SECRET_STORE_ID,
            "secret_name": CLAW_DESKTOP_SECRET_NAME,
        }
    }


def require_exact_web_secrets_store(
    current_bindings: list[dict], *, allow_absent: bool
) -> dict[str, dict[str, str]]:
    """Reject alias collisions, wrong stores, wrong names and partial sets on readback."""
    names = [x.get("name") for x in current_bindings]
    if len(names) != len(set(names)):
        raise ValueError("duplicate Worker binding names")
    expected = expected_web_secret_bindings()
    matches = {b["name"]: b for b in current_bindings if b["name"] in expected}
    for name, item in matches.items():
        if any(item.get(k) != value for k, value in expected[name].items()):
            raise ValueError("web Secrets Store binding identity drift")
    if not allow_absent and set(matches) != set(expected):
        raise ValueError("required web Secrets Store binding missing")
    return {name: item for name, item in expected.items() if name not in matches}
