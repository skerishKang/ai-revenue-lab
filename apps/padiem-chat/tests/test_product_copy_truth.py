from pathlib import Path


STATIC_INDEX = Path(__file__).resolve().parents[1] / "static" / "index.html"


def test_product_surface_does_not_claim_a_model_is_selected_or_auto_routed():
    html = STATIC_INDEX.read_text(encoding="utf-8")

    forbidden = (
        "자동 추천으로 답변합니다",
        "현재 모델 선택",
        "어떤 AI를 쓸지는 파디엠이 자동으로 고릅니다",
        "AI 모델이나 제공 경로는 파디엠이 자동으로 선택합니다",
    )
    for phrase in forbidden:
        assert phrase not in html

    assert "궁금한 것을 평소 말하듯 편하게 물어보세요." in html
    assert "이 지침은 이 프로젝트의 대화에만 적용됩니다." in html


def test_copy_repair_preserves_existing_first_use_dom_hooks():
    html = STATIC_INDEX.read_text(encoding="utf-8")

    required_hooks = (
        'id="messageInput"',
        'id="sendButton"',
        'id="attachmentButton"',
        'id="projectsNavButton"',
        'id="projectDialog"',
        'id="historySection"',
        'id="messageList"',
    )
    for hook in required_hooks:
        assert hook in html
