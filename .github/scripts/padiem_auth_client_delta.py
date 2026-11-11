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
    """Client delta for an operator-reviewed configuration change.

    The reviewed b62-staging client was migrated into the served configuration,
    so this is no longer an addition contract. The client set is stable, every
    client the candidate leaves unchanged keeps its served digest, a changed
    client must match the reviewed target text, and the reviewed staging
    client is never touched.
    """
    proposed = fingerprints(candidate_text)
    reviewed = fingerprints(reviewed_text)
    if not isinstance(live_fingerprints, dict) or not live_fingerprints:
        raise ValueError("live client snapshot unavailable")
    if set(proposed) != set(live_fingerprints):
        raise ValueError("client set differs from live")
    if (STAGING_ID in proposed) != (STAGING_ID in live_fingerprints) or (
            STAGING_ID in proposed and proposed[STAGING_ID] != live_fingerprints[STAGING_ID]):
        raise ValueError("reviewed staging client changed")
    for name, digest in live_fingerprints.items():
        if proposed.get(name) != digest and reviewed.get(name) != proposed.get(name):
            raise ValueError("a changed client does not match the reviewed target")
    return True
