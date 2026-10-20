"""#5247: Chat/Claw error-contract minimal repair regressions.

Three source-verified defects are covered here:

1. ``chat_routes.py`` answered a non-login Free-tier request with a mojibake
   literal (``"?? AI? ????? ???? ???"``) instead of readable Korean.
2. ``claw_general_routes.py`` defined ``_combine_system_context`` twice.
3. ``claw_routes.py`` reflected the caller's own channel/action string into the
   ``invalid_channel`` / ``invalid_action`` messages.

Each regression below fails when its defect is restored. The HTTP status
codes, error codes, and the grade/approval/dispatch contracts are asserted
unchanged, so a repair that weakened them also fails here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.config import Settings

APP_DIR = Path(__file__).resolve().parents[1]
CHAT_ROUTES = APP_DIR / "app" / "chat_routes.py"
CLAW_GENERAL_ROUTES = APP_DIR / "app" / "claw_general_routes.py"
CLAW_ROUTES = APP_DIR / "app" / "claw_routes.py"

# A run of two or more "?" inside one message literal is the signature of a
# Korean string that was written through a lossy ASCII conversion. No real
# user-facing message contains it.
MOJIBAKE_RUN = re.compile(r"\?{2,}")
HANGUL = re.compile(r"[\uac00-\ud7a3]")

FREE_TIER_401_MESSAGE = "무료 AI를 사용하려면 로그인이 필요합니다."
INVALID_CHANNEL_MESSAGE = "지원되지 않는 채널입니다."
INVALID_ACTION_MESSAGE = "지원되지 않는 작업입니다."

# Caller input that must never be reflected back into an error message.
REFLECTED_CHANNEL = "<script>alert('x')</script>"
REFLECTED_ACTION = "<img src=x onerror=alert(1)>"

MANUAL_INTAKE_PATHS = (
    "/api/claw/manual-intake/preview",
    "/api/claw/manual-intake/execute",
)
FREE_TIER_PATHS = ("/api/chat", "/api/chat/stream")


@pytest.fixture
def free_tier_client() -> TestClient:
    """A non-mock runtime with no signed-in member, like Production."""
    settings = Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        live_enabled=False,
        auth_mode="off",
    )
    return TestClient(create_app(settings=settings))


@pytest.fixture
def mock_client() -> TestClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
    )
    return TestClient(create_app(settings=settings))


def _free_tier_payload() -> dict[str, object]:
    return {
        "messages": [{"role": "user", "content": "안녕하세요"}],
        "tier": "free",
    }


# ── 1. the non-login Free-tier 401 message must be readable Korean ─────────


@pytest.mark.parametrize("path", FREE_TIER_PATHS)
def test_free_tier_401_message_is_readable_korean(
    free_tier_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    import app.chat_routes as chat_routes

    async def _grade_gate_did_not_answer(*_args: object, **_kwargs: object) -> None:
        # The shared member-grade gate answers an anonymous tier request
        # first, so the route's own Free-tier guard is normally shadowed.
        # Neutralising that gate here only reaches the guard so that the
        # guard's own message is proven; the product gate is not changed.
        return None

    monkeypatch.setattr(chat_routes, "selected_grade_denial", _grade_gate_did_not_answer)

    resp = free_tier_client.post(path, json=_free_tier_payload())
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "unauthorized"
    message = data["error"]["message"]
    assert message == FREE_TIER_401_MESSAGE
    assert MOJIBAKE_RUN.search(message) is None
    assert HANGUL.search(message)


@pytest.mark.parametrize("path", FREE_TIER_PATHS)
def test_anonymous_free_request_keeps_the_401_contract(
    free_tier_client: TestClient,
    path: str,
) -> None:
    resp = free_tier_client.post(path, json=_free_tier_payload())
    assert resp.status_code == 401
    data = resp.json()
    assert data["error"]["code"] == "unauthorized"
    message = data["error"]["message"]
    assert MOJIBAKE_RUN.search(message) is None
    assert HANGUL.search(message)


def test_chat_routes_carries_no_mojibake_message_literal() -> None:
    tree = ast.parse(CHAT_ROUTES.read_text(encoding="utf-8"))
    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and MOJIBAKE_RUN.search(node.value)
    ]
    assert offenders == []


# ── 2. `_combine_system_context` must be defined exactly once ───────────────


def test_combine_system_context_is_defined_once() -> None:
    tree = ast.parse(CLAW_GENERAL_ROUTES.read_text(encoding="utf-8"))
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_combine_system_context"
    ]
    assert len(definitions) == 1


def test_combine_system_context_keeps_its_join_contract() -> None:
    from app.claw_general_routes import _combine_system_context

    # Order is fixed and empty/absent blocks disappear.
    assert _combine_system_context("grounding", "pc work") == "grounding\n\npc work"
    assert _combine_system_context("a", None, "", "b") == "a\n\nb"
    assert _combine_system_context("a", "b", "c") == "a\n\nb\n\nc"
    assert _combine_system_context("only") == "only"
    assert _combine_system_context(None, "") is None
    assert _combine_system_context() is None


# ── 3. manual intake errors must not reflect caller input ───────────────────


@pytest.mark.parametrize("path", MANUAL_INTAKE_PATHS)
@pytest.mark.parametrize(
    ("field", "value", "code", "message"),
    [
        ("channel", REFLECTED_CHANNEL, "invalid_channel", INVALID_CHANNEL_MESSAGE),
        ("action", REFLECTED_ACTION, "invalid_action", INVALID_ACTION_MESSAGE),
    ],
)
def test_manual_intake_invalid_input_is_not_reflected(
    mock_client: TestClient,
    path: str,
    field: str,
    value: str,
    code: str,
    message: str,
) -> None:
    payload: dict[str, object] = {
        "content": "테스트 본문",
        "channel": "kakao",
        "action": "quote",
    }
    payload[field] = value

    resp = mock_client.post(path, json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == code
    assert data["error"]["message"] == message
    assert value not in data["error"]["message"]
    assert "<" not in data["error"]["message"]


def test_claw_routes_carries_no_reflecting_error_message() -> None:
    """No Claw error message may interpolate a caller-derived value.

    A server-side constant (for example the sender-hint length limit) is a
    fixed part of the contract. A lowercase local such as the caller's own
    channel or action string is caller input and must stay out of the
    response.
    """
    tree = ast.parse(CLAW_ROUTES.read_text(encoding="utf-8"))
    reflected: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id in {"_error", "_error_with_detail"}
        ):
            continue
        for argument in node.args:
            if not isinstance(argument, ast.JoinedStr):
                continue
            for part in argument.values:
                if isinstance(part, ast.FormattedValue):
                    name = part.value
                    if isinstance(name, ast.Name) and not name.id.isupper():
                        reflected.append(f"{node.func.id}: {ast.unparse(argument)}")
    assert reflected == []


def test_manual_intake_normal_request_still_succeeds(mock_client: TestClient) -> None:
    resp = mock_client.post(
        "/api/claw/manual-intake/preview",
        json={
            "content": "가상 테스트: A업체가 샘플 20개 견적서를 요청함.",
            "channel": "kakao",
            "action": "quote",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["preview"]["channel"] == "kakao"
    assert data["preview"]["action"] == "quote_draft"
