"""The COM2 cipher must interoperate with the Worker's WebCrypto AES-GCM."""
import base64
import json
import subprocess

import pytest
from cryptography.exceptions import InvalidTag
from starlette.testclient import TestClient

from app.cpython_aes_gcm import CPythonAesGcmPort
from app.local_cpython import build_app

# Test-only fixed inputs, never production credentials.
KEY = bytes(range(32))
IV = bytes(range(12))
AAD = b"padiem-custom:v3:synthetic:openai:https://example.test/v1"
PLAINTEXT = b'{"api_key":"synthetic-customer-key"}'

NODE_WEBCRYPTO = r"""
const {webcrypto} = require('node:crypto');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  const data = JSON.parse(input);
  const bytes = v => Buffer.from(v, 'base64');
  const key = await webcrypto.subtle.importKey('raw', bytes(data.key), 'AES-GCM', false, [data.mode]);
  const algorithm = {name:'AES-GCM', iv:bytes(data.iv), additionalData:bytes(data.aad), tagLength:128};
  const result = await webcrypto.subtle[data.mode](algorithm, key, bytes(data.input));
  process.stdout.write(Buffer.from(result).toString('base64'));
});
"""


def webcrypto(mode, data):
    enc = lambda b: base64.b64encode(b).decode("ascii")
    payload = dict(mode=mode, key=enc(KEY), iv=enc(IV), aad=enc(AAD), input=enc(data))
    result = subprocess.run(
        ["node", "-e", NODE_WEBCRYPTO], input=json.dumps(payload), text=True,
        capture_output=True, check=True,
    )
    return base64.b64decode(result.stdout)


@pytest.mark.asyncio
async def test_cpython_and_worker_webcrypto_interoperate_in_both_directions():
    cipher = CPythonAesGcmPort()
    nonce = cipher.random_bytes(12)
    assert len(nonce) == 12
    with pytest.raises(ValueError):
        cipher.random_bytes(11)
    sealed = await cipher.encrypt(key=KEY, iv=IV, plaintext=PLAINTEXT, additional_data=AAD)
    assert await cipher.decrypt(key=KEY, iv=IV, ciphertext=sealed, additional_data=AAD) == PLAINTEXT
    assert webcrypto("decrypt", sealed) == PLAINTEXT
    worker_sealed = webcrypto("encrypt", PLAINTEXT)
    assert sealed == worker_sealed
    assert await cipher.decrypt(key=KEY, iv=IV, ciphertext=worker_sealed, additional_data=AAD) == PLAINTEXT
    with pytest.raises(InvalidTag):
        await cipher.decrypt(key=KEY, iv=IV, ciphertext=worker_sealed, additional_data=AAD + b"/other")


def test_com2_host_registers_byok_with_real_cipher(tmp_path, monkeypatch):
    env = {
        "PADIEM_CHAT_CPYTHON_HOST": "1",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2-staging.padiem.net",
        "PADIEM_CHAT_AUTH_MODE": "password",
        "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "PADIEM_CHAT_SESSION_SECRET": "synthetic-session-secret-0123456789",
        "PADIEM_CHAT_CUSTOM_KEY_SECRET": "synthetic-custom-secret-0123456789",
    }
    monkeypatch.delenv("PADIEM_LOCAL_DEV", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    app = build_app()
    app.state.identity_shadow_store = None
    assert isinstance(app.state.custom_credential_store.cipher, CPythonAesGcmPort)
    origin = env["PADIEM_CHAT_PUBLIC_BASE_URL"]
    with TestClient(app, base_url=origin, headers={"Origin": origin}) as client:
        registered = client.post("/api/auth/password/register", json={
            "email": "owner@example.test", "password": "test-password-012345",
        })
        assert registered.status_code == 200, registered.text
        saved = client.put("/api/chat/custom/credential", json={
            "provider": "openai", "api_key": "synthetic-provider-key-012345",
        })
        assert saved.status_code == 200, saved.text
        assert "synthetic-provider-key" not in saved.text
        status = client.get("/api/chat/custom/credential")
        assert status.status_code == 200
        assert status.json()["credentials"][0]["provider"] == "openai"


def test_worker_factory_keeps_existing_cipher_by_default():
    from padiem_control_plane.cloudflare_aes_gcm import CloudflareAesGcmPort
    from app.app_factory import create_app
    from app.config import Settings

    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="off", web_provider="off",
        session_secret="synthetic-session-secret-0123456789",
        custom_key_secret="synthetic-custom-secret-0123456789",
    )
    from types import SimpleNamespace
    app = create_app(settings=settings, d1_binding=SimpleNamespace(prepare=lambda _: None))
    assert isinstance(app.state.custom_credential_store.cipher, CloudflareAesGcmPort)
