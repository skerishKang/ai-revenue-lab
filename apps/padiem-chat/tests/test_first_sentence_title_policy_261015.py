"""First customer input as title for Chat, Claw, and B66. No AI summarizer."""
from app.history import _title_from_user_text, MAX_HISTORY_TITLE_CHARS


def test_first_sentence_is_title_without_summarization():
    assert _title_from_user_text("의자 20개 견적 부탁합니다. 다음 주 납품 예정") == "의자 20개 견적 부탁합니다."
    assert _title_from_user_text("  광주 사무실 의자 20개   ") == "광주 사무실 의자 20개"
    assert _title_from_user_text("\n테스트 장비\n수량 3개") == "테스트 장비"
    assert _title_from_user_text("") == "새 대화"
    assert len(_title_from_user_text("장비" * 100)) == MAX_HISTORY_TITLE_CHARS
