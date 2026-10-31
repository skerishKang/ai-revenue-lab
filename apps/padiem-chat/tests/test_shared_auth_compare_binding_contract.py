import json
from pathlib import Path
import tomllib


def test_compare_bindings_match_gate_baseline_and_default_off():
    root = Path(__file__).resolve().parents[3]
    manifest = tomllib.loads((root / 'apps/padiem-chat/wrangler.toml').read_text())
    baseline = json.loads((root / '.github/binding_baselines/padiem-chat.json').read_text())
    names = {entry['name']:entry['type'] for entry in baseline['bindings']}
    bindings = {entry['binding']:entry for entry in manifest['secrets_store_secrets']}
    for name in ('PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK',
                 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY'):
        assert names[name] == 'secrets_store_secret'
        assert bindings[name]['secret_name'] == name
        assert bindings[name]['store_id'] == 'f0b09ca04a7b43248154c773704a5616'
    assert manifest['vars']['PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED'] == 'false'
    assert names['PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED'] == 'plain_text'
    assert names['PADIEM_CHAT_SHARED_AUTH_CLIENT_KID'] == 'plain_text'
    assert manifest['vars']['PADIEM_CHAT_SHARED_AUTH_CLIENT_KID'] == 'b62-42c57a6725c907f7f3cf'
