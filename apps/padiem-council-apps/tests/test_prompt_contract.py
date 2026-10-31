"""The ported prompt builders keep the shipped util-menu.js templates verbatim.

Golden strings are captured from ``apps/padiem-chat/static/util-menu.js``
(buildPrompt lines ~258-284, SNS gen lines ~700-735, meeting gen ~818-836,
book builder ~868-958) at origin/main ea5f4947d. The meeting book boundary
wording is what ``apps/padiem-chat/tests/test_5785_meeting_tool.py`` pins.
"""

from __future__ import annotations

from types import SimpleNamespace

from _council_module import load_council_module

council = load_council_module()


class FakeFormData(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def form(values: dict) -> FakeFormData:
    return FakeFormData({k: SimpleNamespace(**{}) if False else v for k, v in values.items()})


def test_speech_prompt_matches_the_shipped_template() -> None:
    prompt = council.speech.buildPrompt(form({
        "event": "제78주년 광복절 기념식",
        "date": "2026-08-15",
        "place": "강서문화회관",
        "nature": "지역 행사",
        "audience": "주민 200명",
        "author": "김의원",
        "message": "함께 성장하는 지역사회",
        "emphasis": "상생과 배려",
        "length": "medium",
        "tone": "formal",
        "style": "",
    }))
    assert prompt == (
        "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.\n\n"
        "행사명: 제78주년 광복절 기념식\n"
        "행사 날짜: 2026-08-15\n"
        "장소: 강서문화회관\n"
        "행사 성격: 지역 행사\n"
        "참석 대상: 주민 200명\n"
        "작성자/직책: 김의원\n"
        "주요 메시지: 함께 성장하는 지역사회\n"
        "강조 내용: 상생과 배려\n"
        "분량: 보통(600자 내외)\n"
        "말투: 공식적이고 격식 있는\n"
        "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요."
    )


def test_speech_prompt_keeps_the_style_sample_block_when_present() -> None:
    prompt = council.speech.buildPrompt(form({
        "event": "행사", "date": "", "place": "", "nature": "", "audience": "",
        "author": "", "message": "", "emphasis": "", "length": "short",
        "tone": "warm", "style": "존중하는 시민 여러분",
    }))
    assert "분량: 짧게(300자 내외)" in prompt
    assert "말투: 따뜻하고 친근한" in prompt
    assert "아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:" in prompt
    assert "---\n존중하는 시민 여러분\n---" in prompt


def test_sns_prompt_matches_the_shipped_template_for_each_platform() -> None:
    base = {
        "event": "주민 정원 사업 설명회",
        "whenwhere": "10월 30일 오후 2시, 구청 소회의실",
        "content": "정원 사업 신청 방법과 지원 금액 안내",
        "memo": "",
        "audience": "구내 상인",
        "tone": "professional",
    }
    blog = council.sns.buildPrompt(form(base), "blog")
    assert blog.startswith("다음 행사 정보를 바탕으로 블로그 게시글: 800-1200자, 제목 포함, 소제목 구분, 상세한 설명을 작성해 주세요.\n\n")
    assert "행사명: 주민 정원 사업 설명회\n" in blog
    assert "날짜·장소: 10월 30일 오후 2시, 구청 소회의실\n" in blog
    assert "주요 내용: 정원 사업 신청 방법과 지원 금액 안내\n" in blog
    assert "대상 독자: 구내 상인\n" in blog
    assert "문체: 전문적이고 신뢰감 있는\n" in blog
    assert blog.endswith("제목, 본문, 해시태그를 구분하여 작성해 주세요.")

    facebook = council.sns.buildPrompt(form(base), "facebook")
    assert facebook.startswith("다음 행사 정보를 바탕으로 페이스북 게시글: 300-500자, 친근한 톤, 이모지 적절히, 해시태그 3-5개을 작성해 주세요.")

    instagram = council.sns.buildPrompt(form(base), "instagram")
    assert instagram.startswith("다음 행사 정보를 바탕으로 인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부을 작성해 주세요.")


def test_meeting_prompt_matches_the_shipped_template() -> None:
    prompt = council.meeting.buildPrompt(form({
        "title": "10월 주민 민원 회의",
        "when": "2026-10-24T10:00",
        "attendees": "비서실장, 지역 담당",
        "content": "항구 도로 보수 일정과 버스 노선 조정을 논의했습니다.",
    }))
    assert prompt == (
        "다음 회의 내용을 정리해 주세요.\n\n"
        "회의명: 10월 주민 민원 회의\n"
        "회의 일시: 2026-10-24T10:00\n"
        "참석자: 비서실장, 지역 담당\n"
        "회의 내용:\n항구 도로 보수 일정과 버스 노선 조정을 논의했습니다.\n\n"
        "다음 항목으로 정리해 주세요:\n"
        "1. 회의 요약 (3-5문장)\n"
        "2. 주요 논의사항 (bullet)\n"
        "3. 결정사항 (bullet)\n"
        "4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n"
        "5. 미해결 사항"
    )


def test_book_prompt_keeps_the_no_fabrication_boundary() -> None:
    prompt = council.meeting.buildBookPrompt(["[기록: 10월 주민 민원 회의.txt]\n본문"])
    assert prompt.startswith("다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.")
    assert "[기록: 10월 주민 민원 회의.txt]\n본문" in prompt
    assert "1. 책/활동집 제목 후보 3개" in prompt
    assert "2. 목차 (5-8장)" in prompt
    assert "3. 각 장별 원고 초안 (200-400자)" in prompt
    assert "4. 마무리 인사" in prompt
    # The boundary wording pinned by apps/padiem-chat tests/test_5785_meeting_tool.py.
    assert "원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요" in prompt
    assert "각 장 끝에 근거가 된 기록 파일명을 표시하세요" in prompt
