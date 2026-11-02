"""#6709 Free transient-5xx retry and COM2 central-admin host wiring."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = (ROOT / "app" / "orchestration_bridge.py").read_text(encoding="utf-8")
LOCAL = (ROOT / "app" / "local_cpython.py").read_text(encoding="utf-8")


def test_the_free_platform_lane_allows_one_same_route_retry():
    # A transient provider 5xx must retry the declared model once before the
    # B14 fallback chain can spend the turn on a slower fallback model.
    assert (
        '"model_policy": {"model": model_id, "max_retries": 0 if byok_selection is not None else 1},'
        in BRIDGE
    )
    # BYOK spends the caller's own key and keeps its no-retry contract.
    assert 'request["max_retries"] = 0' in BRIDGE


def test_the_local_host_reads_the_central_admin_email_setting():
    assert (
        'central_model_admin_google_email=os.getenv(\n'
        '            "PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL", ""\n'
        '        ).strip(),'
        in LOCAL
    )
