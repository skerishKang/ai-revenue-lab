import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"))
from com2_edge_proof import EdgeProofVerifier


def test_javascript_signer_fixture_is_accepted_and_replay_rejected(tmp_path):
    verifier = EdgeProofVerifier("synthetic-only-secret-0123456789", str(tmp_path / "replay.sqlite"))
    headers = {
        "x-padiem-edge-at": "1700000000",
        "x-padiem-edge-id": "0123456789abcdef0123456789abcdef",
        "x-padiem-edge-tls": "TLSv1.3",
        "x-padiem-edge-proof": "v1=ae41f2e13728a2ac4013ac7864e2621f96cf202f13a5fee3ceb79001d36ced0a",
    }
    kwargs = dict(method="GET", path="/api/claw/connector/gateway/session", headers=headers, now=1700000000)
    assert verifier.verify(**kwargs)
    assert not verifier.verify(**kwargs)
