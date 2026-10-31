import hashlib
import hmac

from com2_edge_proof import EdgeProofVerifier

SECRET = "synthetic-test-" + "x" * 32
PATH = "/api/claw/connector/gateway/session"


def headers(request_id="a" * 32, at=1000, tls="TLSv1.3", path=PATH):
    signed = "\n".join(("v1", "GET", path, str(at), request_id, tls)).encode()
    proof = "v1=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-edge-at": str(at), "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": tls, "x-padiem-edge-proof": proof}


def test_valid_invalid_stale_and_durable_replay(tmp_path):
    db = str(tmp_path / "replay.sqlite3")
    verifier = EdgeProofVerifier(SECRET, db)
    good = headers()
    assert verifier.verify(method="GET", path=PATH, headers={}, now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=dict(good, **{"x-padiem-edge-proof": "v1=" + "0" * 64}), now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=headers("b" * 32, at=699), now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=headers("b" * 32), now=1000) is True
    assert EdgeProofVerifier(SECRET, db).verify(method="GET", path=PATH, headers=headers("b" * 32), now=1001) is False
    assert verifier.verify(method="GET", path=PATH, headers=good, now=1000) is True
    assert verifier.verify(method="GET", path="/other", headers=headers("c" * 32), now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=headers("d" * 32, tls="TLSv1.0"), now=1000) is False
