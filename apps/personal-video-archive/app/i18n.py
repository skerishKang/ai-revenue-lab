"""Bilingual string catalog for Personal Video Archive.

Korean is the default locale. English mirrors every key under ``/en/``.
"""

from __future__ import annotations

SUPPORTED_LOCALES = ("ko", "en")
DEFAULT_LOCALE = "ko"

STRINGS: dict[str, dict[str, str]] = {
    # --- Brand ------------------------------------------------------------
    "app_name": {"ko": "나의 영상 아카이브", "en": "Personal Video Archive"},
    # --- Navigation -------------------------------------------------------
    "nav_home": {"ko": "홈", "en": "Home"},
    "nav_topics": {"ko": "토픽", "en": "Topics"},
    "nav_records": {"ko": "나의 기록", "en": "My Records"},
    "nav_proposals": {"ko": "AI 제안", "en": "AI Suggestions"},
    "lang_switch": {"ko": "English", "en": "한국어"},
    # --- Home -------------------------------------------------------------
    "home_subtitle": {
        "ko": "주제별 영상 발견과 나만의 기록",
        "en": "Topic-first video discovery and private reflection",
    },
    "home_continue_watching": {"ko": "이어 보기", "en": "Continue Watching"},
    "home_new_finds": {"ko": "새로 발견한 영상", "en": "New Finds"},
    "home_topics": {"ko": "토픽", "en": "Topics"},
    "home_recent_notes": {"ko": "최근 기록", "en": "Recent Notes"},
    "home_resurfaced": {"ko": "다시 떠오른 기록", "en": "Resurfaced"},
    "home_see_all": {"ko": "전체 보기", "en": "See all"},
    "home_empty": {"ko": "아직 기록이 없습니다", "en": "No records yet"},
    "home_empty_desc": {
        "ko": "영상을 보고 기록을 시작하세요.",
        "en": "Watch videos and start recording.",
    },
    # --- Topics -----------------------------------------------------------
    "topics_title": {"ko": "토픽", "en": "Topics"},
    "topic_created": {"ko": "생성일", "en": "Created"},
    "topic_archived": {"ko": "보관됨", "en": "Archived"},
    # --- Feed -------------------------------------------------------------
    "feed_refresh": {"ko": "피드 새로고침", "en": "Refresh Feed"},
    "feed_my_records": {"ko": "나의 기록", "en": "My Records"},
    "feed_newest_first": {"ko": "최신순", "en": "Newest First"},
    "feed_showing": {"ko": "영상 {n}개", "en": "Showing {n} videos"},
    "feed_match_score": {"ko": "매칭 {score}%", "en": "match {score}%"},
    "feed_why_recommended": {
        "ko": "이 영상이 추천된 이유",
        "en": "Why this video was recommended",
    },
    "feed_published": {"ko": "게시일", "en": "Published"},
    "feed_duration_min": {"ko": "분", "en": "min"},
    "feed_views": {"ko": "조회수", "en": "views"},
    "feed_sync_failed_title": {"ko": "새로고침 실패", "en": "Refresh failed"},
    "feed_sync_failed_desc": {
        "ko": "영상 제공 서비스에 연결할 수 없어 새 영상을 가져오지 못했습니다. "
        "기존 목록은 그대로 유지됩니다. 잠시 후 다시 시도해 주세요.",
        "en": "Could not connect to the video service to fetch new videos. "
        "Your existing list is preserved. Please try again later.",
    },
    # --- Viewing states ---------------------------------------------------
    "state_all": {"ko": "전체", "en": "All"},
    "state_unseen": {"ko": "아직 보지 않음", "en": "Not yet watched"},
    "state_opened": {"ko": "열어봄", "en": "Opened"},
    "state_saved": {"ko": "저장함", "en": "Saved"},
    "state_in_progress": {"ko": "보는 중", "en": "Watching"},
    "state_completed": {"ko": "다 봄", "en": "Completed"},
    "state_revisit": {"ko": "다시 보기", "en": "Revisit"},
    "state_irrelevant": {"ko": "관심 없음", "en": "Not interested"},
    # --- Actions ----------------------------------------------------------
    "action_open_youtube": {"ko": "YouTube에서 열기", "en": "Open on YouTube"},
    "action_create_record": {"ko": "기록 만들기", "en": "Create Record"},
    "action_save": {"ko": "저장", "en": "Save"},
    "action_cancel": {"ko": "취소", "en": "Cancel"},
    "action_search": {"ko": "검색", "en": "Search"},
    "action_accept": {"ko": "수락", "en": "Accept"},
    "action_reject": {"ko": "거절", "en": "Reject"},
    "action_generate_rules": {"ko": "검색 규칙 생성", "en": "Generate Search Rules"},
    "action_accept_create": {
        "ko": "수락하고 토픽 피드 만들기",
        "en": "Accept and Create Topic Feed",
    },
    "action_generate_proposal": {"ko": "제안 생성", "en": "Generate Proposal"},
    "action_go_home": {"ko": "홈으로", "en": "Go Home"},
    "action_create_topic": {"ko": "토픽 만들기", "en": "Create Topic"},
    # --- Provenance badges ------------------------------------------------
    "badge_youtube": {"ko": "YouTube 정보", "en": "YouTube info"},
    "badge_app": {"ko": "이 영상이 추천된 이유", "en": "Why recommended"},
    "badge_user": {"ko": "나의 기록", "en": "My record"},
    "badge_ai": {"ko": "AI 정리 제안", "en": "AI suggestion"},
    # --- Preview notice ---------------------------------------------------
    "preview_notice": {
        "ko": "미리보기 · 예시 데이터 · 저장되지 않음",
        "en": "Preview · Sample data · Nothing is saved",
    },
    # --- Empty states -----------------------------------------------------
    "empty_topics_title": {"ko": "아직 토픽이 없습니다", "en": "No topics yet"},
    "empty_topics_desc": {
        "ko": "첫 토픽을 만들어 주제별로 영상을 발견하세요.",
        "en": "Create your first topic to start discovering videos by subject.",
    },
    "empty_videos_title": {"ko": "아직 영상이 없습니다", "en": "No videos yet"},
    "empty_videos_desc": {
        "ko": "'피드 새로고침'을 눌러 이 토픽의 영상을 발견하세요.",
        "en": 'Click "Refresh Feed" to discover videos for this topic.',
    },
    "empty_records_title": {"ko": "기록이 없습니다", "en": "No records found"},
    "empty_records_desc": {
        "ko": "검색 조건을 조정해 보세요.",
        "en": "Try adjusting your search filters.",
    },
    "empty_proposals_title": {
        "ko": "대기 중인 제안이 없습니다",
        "en": "No pending proposals",
    },
    "empty_proposals_desc": {
        "ko": "모든 AI 제안을 검토했습니다.",
        "en": "All AI suggestions have been reviewed.",
    },
    # --- Forms ------------------------------------------------------------
    "form_topic_name": {"ko": "토픽 이름", "en": "Topic Name"},
    "form_topic_name_ph": {"ko": "예: ChatGPT 업데이트", "en": "e.g. ChatGPT updates"},
    "form_intent": {"ko": "자연어 의도", "en": "Natural-Language Intent"},
    "form_intent_ph": {
        "ko": "팔로우하고 싶은 내용을 설명하세요.",
        "en": "Describe what you want to follow.",
    },
    "form_intent_help": {
        "ko": "AI가 이 내용을 검색 규칙 초안으로 변환합니다.",
        "en": "The AI will convert this into a search-rule draft for your review.",
    },
    "form_primary_query": {"ko": "기본 검색어", "en": "Primary Search Term"},
    "form_related_queries": {
        "ko": "관련 검색어 (쉼표로 구분)",
        "en": "Related Queries (comma-separated)",
    },
    "form_related_queries_help": {
        "ko": "토픽을 포착하는 추가 검색어입니다.",
        "en": "Additional search terms that capture the topic.",
    },
    "form_required_terms": {
        "ko": "필수 포함 단어 (쉼표로 구분)",
        "en": "Required Terms (comma-separated)",
    },
    "form_required_terms_help": {
        "ko": "영상에 이 단어 중 하나 이상이 포함되어야 합니다.",
        "en": "Videos must contain at least one of these terms.",
    },
    "form_excluded_terms": {
        "ko": "제외 단어 (쉼표로 구분)",
        "en": "Excluded Terms (comma-separated)",
    },
    "form_excluded_terms_help": {
        "ko": "이 단어가 포함된 영상은 필터링됩니다.",
        "en": "Videos containing these terms will be filtered out.",
    },
    "form_preferred_languages": {
        "ko": "선호 언어 (쉼표로 구분)",
        "en": "Preferred Languages (comma-separated)",
    },
    "form_included_channels": {
        "ko": "포함 채널 (쉼표로 구분)",
        "en": "Included Channels (comma-separated)",
    },
    "form_excluded_channels": {
        "ko": "제외 채널 (쉼표로 구분)",
        "en": "Excluded Channels (comma-separated)",
    },
    "form_duration": {"ko": "길이", "en": "Duration"},
    "form_duration_any": {"ko": "제한 없음", "en": "Any"},
    "form_duration_short": {"ko": "짧음", "en": "Short"},
    "form_duration_medium": {"ko": "중간", "en": "Medium"},
    "form_duration_long": {"ko": "김", "en": "Long"},
    "form_shorts": {"ko": "쇼츠", "en": "Shorts"},
    "form_shorts_include": {"ko": "포함", "en": "Include"},
    "form_shorts_exclude": {"ko": "제외", "en": "Exclude"},
    "form_default_sort": {"ko": "기본 정렬", "en": "Default Sort"},
    "form_sort_newest": {"ko": "최신순", "en": "Newest First"},
    "form_sort_relevance": {"ko": "관련도순", "en": "Relevance"},
    "form_sort_views": {"ko": "조회수순", "en": "View Count"},
    "form_date_start": {"ko": "기간 시작", "en": "Date Window Start"},
    "form_date_start_help": {
        "ko": "선택 사항. 이 날짜 이후에 게시된 영상만 표시합니다.",
        "en": "Optional. Only videos published on or after this date.",
    },
    "form_date_end": {"ko": "기간 종료", "en": "Date Window End"},
    "form_date_end_help": {
        "ko": "선택 사항. 이 날짜 이전에 게시된 영상만 표시합니다.",
        "en": "Optional. Only videos published on or before this date.",
    },
    "form_viewing_state": {"ko": "시청 상태", "en": "Viewing State"},
    "form_rating": {"ko": "평점 (1-5)", "en": "Rating (1-5)"},
    "form_opened_date": {"ko": "처음 연 날짜", "en": "Opened Date"},
    "form_completed_date": {"ko": "완료 날짜", "en": "Completed Date"},
    "form_free_note": {
        "ko": "자유 메모 (원본 텍스트 보존)",
        "en": "Free-Form Note (original text preserved)",
    },
    "form_free_note_help": {
        "ko": "이것은 당신의 원본 텍스트입니다. AI 제안에 의해 덮어쓰이지 않습니다.",
        "en": "This is your original text. It is never overwritten by AI suggestions.",
    },
    "form_free_note_ph": {
        "ko": "대략적인 생각, 메모, 관찰...",
        "en": "Your rough thoughts, notes, or observations...",
    },
    "form_reflection": {"ko": "회고", "en": "Reflection"},
    "form_learned": {"ko": "배운 점", "en": "What I Learned"},
    "form_agreement": {"ko": "동의하는 부분", "en": "Agreement"},
    "form_disagreement": {
        "ko": "동의하지 않는 부분",
        "en": "Disagreement / Uncertainty",
    },
    "form_uncertainty": {"ko": "불확실한 부분", "en": "Uncertainty"},
    "form_follow_up": {"ko": "후속 계획", "en": "Follow-Up Plan"},
    "form_tags": {"ko": "태그 (쉼표로 구분)", "en": "Tags (comma-separated)"},
    "form_timestamps": {"ko": "타임스탬프 참조", "en": "Timestamp References"},
    "form_search_ph": {
        "ko": "메모, 회고, 계획 검색...",
        "en": "Search notes, reflections, plans...",
    },
    "form_all_states": {"ko": "전체 상태", "en": "All States"},
    "form_tags_ph": {
        "ko": "태그 (쉼표로 구분)",
        "en": "Tags (comma-separated)",
    },
    "form_rough_notes_ph": {
        "ko": "대략적인 시청 메모를 여기에 붙여넣으세요...",
        "en": "Paste your rough viewing notes here...",
    },
    # --- Pages ------------------------------------------------------------
    "page_review_rules": {"ko": "검색 규칙 검토", "en": "Review Search Rules"},
    "page_review_rules_desc": {
        "ko": "AI가 당신의 의도로부터 이 규칙을 생성했습니다. 수락 전에 모든 필드를 "
        "편집할 수 있습니다. 승인하기 전에는 아무것도 저장되지 않습니다.",
        "en": "These rules were generated from your intent. Edit any field before "
        "accepting. Nothing is saved until you approve.",
    },
    "page_rationale": {"ko": "근거", "en": "Rationale"},
    "page_new_topic": {"ko": "토픽 만들기", "en": "Create Topic"},
    "page_video_info": {"ko": "영상 정보", "en": "Video Information"},
    "page_topics_section": {"ko": "토픽", "en": "Topics"},
    "page_viewing_records": {"ko": "시청 기록", "en": "Viewing Records"},
    "page_record_title": {"ko": "시청 기록", "en": "Viewing Record"},
    "page_ai_structure": {"ko": "AI 구조화 제안", "en": "AI Structure Proposal"},
    "page_ai_structure_desc": {
        "ko": "아래에 대략적인 메모를 붙여넣으면 AI가 구조화된 기록을 제안합니다. "
        "제안은 검토를 위해 표시되며, 수락하기 전에는 적용되지 않습니다.",
        "en": "Paste rough notes below to get an AI-suggested structured record. "
        "The proposal appears for your review — nothing is applied until you accept.",
    },
    "page_pending_proposals": {"ko": "대기 중인 제안", "en": "Pending Proposals"},
    "page_preview_proposal": {"ko": "제안 미리보기", "en": "Preview proposal"},
    "page_preview_json": {
        "ko": "제안 JSON 미리보기",
        "en": "Preview proposal JSON",
    },
    "page_proposals_title": {"ko": "대기 중인 제안", "en": "Pending Proposals"},
    "page_records_title": {"ko": "나의 기록", "en": "My Records"},
    "page_error": {"ko": "오류", "en": "Error"},
    "page_health": {"ko": "상태", "en": "Health"},
    "page_preview_landing": {
        "ko": "UI 상태 미리보기",
        "en": "UI State Preview",
    },
    "page_preview_landing_desc": {
        "ko": "정적 미리보기의 모든 페이지를 탐색합니다.",
        "en": "Explore all pages in the static preview.",
    },
    # --- QA preview index sections ----------------------------------------
    "qa_section_1": {
        "ko": "토픽 만들기 & 규칙 검토",
        "en": "Create topic & review rule",
    },
    "qa_section_2": {"ko": "토픽 피드 살펴보기", "en": "Inspect topic feed"},
    "qa_section_3": {
        "ko": "소스 열기 & 영상 상세",
        "en": "Open source & video detail",
    },
    "qa_section_4": {
        "ko": "개인 기록 & AI 제안",
        "en": "Private records & AI suggestions",
    },
    "qa_section_5": {
        "ko": "오류 & 시스템 상태",
        "en": "Error & system states",
    },
    "qa_home": {"ko": "제품 홈", "en": "Product home"},
    "qa_topics_page": {"ko": "토픽 페이지", "en": "Topics page"},
    "qa_new_topic": {"ko": "새 토픽 폼", "en": "New topic form"},
    "qa_review_rule": {"ko": "검색 규칙 검토", "en": "Search rule review"},
    "qa_populated_feed": {"ko": "영상 있는 피드", "en": "Populated feed"},
    "qa_feed_unseen": {
        "ko": "아직 보지 않음 필터",
        "en": "Filtered to unseen",
    },
    "qa_feed_completed": {"ko": "다 봄 필터", "en": "Filtered to completed"},
    "qa_empty_feed": {"ko": "빈 피드", "en": "Empty feed"},
    "qa_refresh_failed": {"ko": "새로고침 실패", "en": "Refresh failure"},
    "qa_video_detail": {"ko": "영상 상세", "en": "Video detail"},
    "qa_record_edit": {
        "ko": "기록 상세 / 편집",
        "en": "Record detail / edit",
    },
    "qa_record_proposal": {
        "ko": "대기 중인 AI 제안",
        "en": "Pending AI proposal",
    },
    "qa_record_structured": {"ko": "구조화된 기록", "en": "Structured record"},
    "qa_record_search": {"ko": "기록 검색", "en": "Record search"},
    "qa_error_example": {
        "ko": "검증 오류 예시",
        "en": "Validation error example",
    },
    "qa_health": {"ko": "상태 (합성)", "en": "Health (synthetic)"},
    "qa_workflow": {
        "ko": "워크플로: 토픽 만들기 → 규칙 검토 → 피드 살펴보기 → 소스 열기 → "
        "기록 만들기 → AI 제안 검토",
        "en": "Workflow: create topic → review rule → inspect feed → open source → "
        "create record → review AI suggestion",
    },
    # --- Health -----------------------------------------------------------
    "health_status": {"ko": "상태: 정상 (합성)", "en": "Status: ok (synthetic)"},
    "health_discovery": {
        "ko": "영상 발견 제공자",
        "en": "Discovery provider",
    },
    "health_llm": {"ko": "LLM 제공자", "en": "LLM provider"},
    "health_note": {
        "ko": "정적 UI 미리보기를 위한 합성 상태 스냅샷입니다. "
        "실제 서비스, 데이터베이스, 제공자에 접속하지 않습니다.",
        "en": "Synthetic health snapshot for the static UI preview. No live service, "
        "database, or provider is contacted.",
    },
}


def make_t(locale: str):
    """Return a translation function bound to *locale*."""

    def t(key: str, **kwargs: object) -> str:
        entry = STRINGS.get(key)
        if entry is None:
            return key
        text = entry.get(locale, entry.get(DEFAULT_LOCALE, key))
        if kwargs:
            return text.format(**kwargs)
        return text

    return t


def locale_from_path(path: str) -> str:
    """Derive the locale from a request path."""
    if path == "/en" or path.startswith("/en/"):
        return "en"
    return "ko"


def locale_prefix(locale: str) -> str:
    """URL prefix for a locale (empty string for the default Korean locale)."""
    return "/en" if locale == "en" else ""


def lang_switch_href(path: str, query: str = "") -> str:
    """Compute the href that switches to the other locale, preserving path + query."""
    if path == "/en" or path.startswith("/en/"):
        switch = path[3:] or "/"
    else:
        switch = "/en" + path
    if query:
        return f"{switch}?{query}"
    return switch
