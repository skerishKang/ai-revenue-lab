"""Shared STT contract: provider order, turn model, dedup and utterance identity.

Pins the runtime-agnostic rules ported from
``skerishKang/global-classroom`` (``hooks/useInterviewLive.ts`` and
``utils/liveTranscriptTurn.ts``). These are the rules Chat, Claw and B66 must
share; a divergent copy is what produced the #87 regression.
"""

from __future__ import annotations

import pytest

import voice_stt_contract as c


def test_provider_order_is_gemini_browser_groq():
    assert c.STT_PROVIDER_ORDER == (
        c.SttProvider.GEMINI_LIVE,
        c.SttProvider.BROWSER_SPEECH,
        c.SttProvider.GROQ_WHISPER,
    )


def test_fallback_chain_is_one_way_and_ends():
    assert c.next_provider(None) is c.SttProvider.GEMINI_LIVE
    assert c.next_provider(c.SttProvider.GEMINI_LIVE) is c.SttProvider.BROWSER_SPEECH
    assert c.next_provider(c.SttProvider.BROWSER_SPEECH) is c.SttProvider.GROQ_WHISPER
    assert c.next_provider(c.SttProvider.GROQ_WHISPER) is None


def test_only_server_side_providers_need_a_secret():
    assert c.provider_is_server_side(c.SttProvider.GEMINI_LIVE)
    assert c.provider_is_server_side(c.SttProvider.GROQ_WHISPER)
    assert not c.provider_is_server_side(c.SttProvider.BROWSER_SPEECH)


def test_only_final_is_authoritative_input():
    interim = c.TranscriptEvent("s:0:0", c.TranscriptKind.INTERIM, "안녕", c.SttProvider.GEMINI_LIVE)
    final = c.TranscriptEvent("s:0:0", c.TranscriptKind.FINAL, "안녕하세요", c.SttProvider.GEMINI_LIVE)
    blank = c.TranscriptEvent("s:0:1", c.TranscriptKind.FINAL, "   ", c.SttProvider.GEMINI_LIVE)
    assert not interim.is_authoritative
    assert final.is_authoritative
    assert not blank.is_authoritative


def test_utterance_id_is_deterministic_across_provider_switch():
    first = c.make_utterance_id("sess-1", 0, 3)
    again = c.make_utterance_id("sess-1", 0, 3)
    assert first == again == "sess-1:0:3"


def test_utterance_id_rejects_unsafe_session_ids():
    with pytest.raises(ValueError):
        c.make_utterance_id("", 0, 0)
    with pytest.raises(ValueError):
        c.make_utterance_id("bad id with spaces", 0, 0)
    with pytest.raises(ValueError):
        c.make_utterance_id("sess", -1, 0)


def test_deduper_drops_refinalised_row_from_fallback():
    deduper = c.TranscriptDeduper()
    utterance = c.make_utterance_id("sess", 0, 0)
    browser = c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, "How are you", c.SttProvider.BROWSER_SPEECH)
    groq = c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, "How are you", c.SttProvider.GROQ_WHISPER)
    assert deduper.accept(browser) is True
    # The fallback re-finalises the SAME utterance under the same id -> dropped.
    assert deduper.accept(groq) is False


def test_deduper_keeps_two_distinct_utterances_with_identical_text():
    deduper = c.TranscriptDeduper()
    one = c.TranscriptEvent(c.make_utterance_id("s", 0, 0), c.TranscriptKind.FINAL, "네", c.SttProvider.GEMINI_LIVE)
    two = c.TranscriptEvent(c.make_utterance_id("s", 0, 1), c.TranscriptKind.FINAL, "네", c.SttProvider.GEMINI_LIVE)
    assert deduper.accept(one) is True
    assert deduper.accept(two) is True


def test_deduper_never_suppresses_interim():
    deduper = c.TranscriptDeduper()
    utterance = c.make_utterance_id("s", 0, 0)
    interim = c.TranscriptEvent(utterance, c.TranscriptKind.INTERIM, "안", c.SttProvider.GEMINI_LIVE)
    final = c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, "안녕", c.SttProvider.GEMINI_LIVE)
    assert deduper.accept(interim) is True
    assert deduper.accept(interim) is True
    assert deduper.accept(final) is True


def test_submission_guard_submits_an_utterance_at_most_once():
    guard = c.UtteranceSubmissionGuard()
    utterance = c.make_utterance_id("s", 0, 0)
    assert guard.claim(utterance) is True
    assert guard.claim(utterance) is False
    assert guard.submitted(utterance) is True
    # A deliberate retry after a rejected submission is possible.
    guard.release(utterance)
    assert guard.claim(utterance) is True


def test_submission_guard_keeps_distinct_utterances_independent():
    guard = c.UtteranceSubmissionGuard()
    assert guard.claim(c.make_utterance_id("s", 0, 0)) is True
    assert guard.claim(c.make_utterance_id("s", 0, 1)) is True


def test_merge_handles_delta_and_cumulative_hypotheses():
    assert c.merge_transcript_chunk("", "abc") == "abc"
    assert c.merge_transcript_chunk("abc", "") == "abc"
    # Cumulative hypothesis: incoming supersedes the seen prefix.
    assert c.merge_transcript_chunk("abc", "abcdef") == "abcdef"
    # Repeated suffix must not duplicate.
    assert c.merge_transcript_chunk("abcdef", "def") == "abcdef"
    # True delta appends.
    assert c.merge_transcript_chunk("abc", "def") == "abcdef"


def test_turn_buffer_commits_one_row_and_is_idempotent():
    buffer = c.TranscriptTurnBuffer()
    buffer.merge("Could you tell me ")
    buffer.merge("which bus goes to ")
    buffer.merge("the station")
    assert buffer.pending == "Could you tell me which bus goes to the station"
    assert buffer.finish_turn() == "Could you tell me which bus goes to the station"
    # A second boundary must not duplicate the row.
    assert buffer.finish_turn() is None
    assert buffer.pending == ""


def test_turn_buffer_handles_cumulative_hypotheses_without_duplication():
    buffer = c.TranscriptTurnBuffer()
    buffer.merge("Hello")
    buffer.merge("Hello world")
    buffer.merge("Hello world again")
    assert buffer.finish_turn() == "Hello world again"


def test_handoff_buffer_bounds_and_counts_drops():
    buffer = c.AudioHandoffBuffer(max_frames=2)
    assert buffer.push(b"a") is False  # not capturing yet
    buffer.start()
    assert buffer.push(b"a") is True
    assert buffer.push(b"b") is True
    assert buffer.push(b"c") is False  # cap reached
    assert buffer.dropped_frames == 1
    assert buffer.release() == [b"a", b"b"]
    assert buffer.capturing is False
    assert buffer.size == 0


def test_tail_flush_recovers_clause_and_never_double_settles():
    settled: list[str | None] = []
    timers: list[object] = []

    def set_timer(_cb, _ms):
        token = object()
        timers.append(token)
        return token

    flush = c.LiveTailFlush(
        on_settled=settled.append,
        send_audio_stream_end=lambda: None,
        set_timer=set_timer,
        clear_timer=lambda _t: None,
    )
    assert flush.armed is True
    # A delta tail, then a bare boundary with no text must not close it.
    assert flush.accept("experience.") is True
    assert flush.accept(None, finished=True) is True
    assert settled == ["experience."]
    assert flush.armed is False
    assert flush.accept("late", finished=True) is False
    assert settled == ["experience."]


def test_tail_flush_cancel_still_reports_captured_text():
    settled: list[str | None] = []
    flush = c.LiveTailFlush(
        on_settled=settled.append,
        send_audio_stream_end=lambda: None,
        set_timer=lambda _cb, _ms: object(),
        clear_timer=lambda _t: None,
    )
    flush.accept("tail words")
    flush.cancel()
    assert settled == ["tail words"]


def test_tail_flush_empty_tail_settles_to_none():
    settled: list[str | None] = []
    flush = c.LiveTailFlush(
        on_settled=settled.append,
        send_audio_stream_end=lambda: None,
        set_timer=lambda _cb, _ms: object(),
        clear_timer=lambda _t: None,
    )
    flush.cancel()
    assert settled == [None]


def test_groq_chunk_is_cut_at_a_pause_not_a_fixed_clock():
    # The old fixed 5500ms stop: no pause yet -> must NOT cut.
    assert c.should_cut_groq_chunk(elapsed_ms=5_500, silence_ms=0) is False
    assert c.should_cut_groq_chunk(elapsed_ms=5_500, silence_ms=300) is False
    # Below the minimum window: even a pause must not cut.
    assert c.should_cut_groq_chunk(elapsed_ms=3_000, silence_ms=1_500) is False
    # Real pause after the minimum window: cut.
    assert c.should_cut_groq_chunk(elapsed_ms=5_000, silence_ms=800) is True
    # Hard maximum always cuts so the payload stays bounded.
    assert c.should_cut_groq_chunk(elapsed_ms=20_000, silence_ms=0) is True


def test_stall_flush_only_with_pending_text():
    assert c.should_flush_stalled_turn(has_pending=False, since_last_chunk_ms=9_999) is False
    assert c.should_flush_stalled_turn(has_pending=True, since_last_chunk_ms=100) is False
    assert c.should_flush_stalled_turn(has_pending=True, since_last_chunk_ms=2_500) is True


def test_recognition_language_prefers_hint_then_observed_then_locale():
    assert c.resolve_recognition_language(hint="en", observed="ko", navigator_language="ko-KR") == "en"
    assert c.resolve_recognition_language(observed="en", navigator_language="ko-KR") == "en"
    # 'auto' is not a usable SpeechRecognition tag.
    assert c.resolve_recognition_language(hint="auto", observed="en") == "en"
    assert c.resolve_recognition_language(navigator_language="en-US") == "en-US"
    assert c.resolve_recognition_language() == "ko-KR"


def test_vad_window_is_widened_from_the_650ms_regression():
    assert c.GEMINI_LIVE_VAD_SILENCE_MS == 1_300
    assert c.GEMINI_LIVE_SESSION_ROTATE_MS == 9 * 60_000 + 20_000
