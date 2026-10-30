"""Compare client entries by canonical digests, never output configuration values."""
import hashlib
import json

STAGING_ID = "b62-staging"


def _object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate client configuration key")
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=pairs)
    if not isinstance(value, dict) or not value:
        raise ValueError("invalid client configuration")
    return value


def fingerprints(text):
    clients = _object(text)
    if any(not isinstance(k, str) or not isinstance(v, dict) for k, v in clients.items()):
        raise ValueError("invalid client entry")
    return {name: hashlib.sha256(json.dumps(
        entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest() for name, entry in clients.items()}


def verify_delta(live_fingerprints, candidate_text, reviewed_text):
    proposed = fingerprints(candidate_text)
    reviewed = fingerprints(reviewed_text)
    if not isinstance(live_fingerprints, dict) or not live_fingerprints:
        raise ValueError("live client snapshot unavailable")
    if STAGING_ID in live_fingerprints:
        raise ValueError("staging client already exists")
    if set(proposed) != set(live_fingerprints) | {STAGING_ID}:
        raise ValueError("client set differs from approved addition")
    if any(proposed[name] != digest for name, digest in live_fingerprints.items()):
        raise ValueError("an existing client changed")
    if STAGING_ID not in reviewed or proposed[STAGING_ID] != reviewed[STAGING_ID]:
        raise ValueError("staging client differs from reviewed configuration")
    return True
