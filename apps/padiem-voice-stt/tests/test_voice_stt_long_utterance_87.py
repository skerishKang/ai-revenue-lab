"""Long-utterance truncation regression (global-classroom #87).

Global Classroom #87 is still OPEN: a 20-40 second English sentence with
ordinary thinking pauses was emitted as several partial final rows
("Could you tell me which", "Taste the refreshing", ...) instead of one row,
and the Groq fallback force-stopped recording every 5500ms regardless of speech
boundaries, physically clipping long questions.

This suite proves the PADIEM contract does **not** reproduce that failure. It is
the load-bearing test for the task requirement "긴 발화 잘림 문제(#87)를 그대로
복제하지 않도록 테스트한다".
"""

from __future__ import annotations

import voice_stt_contract as c

# A single long English sentence with a known ground truth, roughly 28 seconds
# of speech. The pauses sit at the ordinary comma/thought boundaries.
GROUND_TRUTH = (
    "Could you tell me which bus goes to the central station "
    "and whether I need to transfer somewhere in the middle "
    "because I have a heavy suitcase "
    "and I would rather not climb any stairs "
    "if there is another route that avoids them"
)
# Deltas as a Live transcriber would emit them, with the pause (ms) that follows
# each delta. These are ordinary 0.7-1.2s thinking pauses.
DELTAS: tuple[tuple[str, int], ...] = (
    ("Could you tell me which bus goes to the central station ", 1200),
    ("and whether I need to transfer somewhere in the middle ", 900),
    ("because I have a heavy suitcase ", 1100),
    ("and I would rather not climb any stairs ", 700),
    ("if there is another route that avoids them", 400),
)


def _replay_turns(vad_silence_ms: int) -> list[str]:
    """Replay the deltas through the shared turn buffer at a given VAD window."""
    buffer = c.TranscriptTurnBuffer()
    rows: list[str] = []
    for delta, pause_ms in DELTAS:
        buffer.merge(delta)
        if c.live_turn_boundary_reached(pause_ms, vad_silence_ms):
            committed = buffer.finish_turn()
            if committed:
                rows.append(committed)
    committed = buffer.finish_turn()
    if committed:
        rows.append(committed)
    return rows


def test_long_sentence_is_one_row_at_the_shared_vad_window():
    rows = _replay_turns(c.GEMINI_LIVE_VAD_SILENCE_MS)
    assert rows == [GROUND_TRUTH], rows


def test_old_650ms_window_would_have_split_the_sentence():
    """The exact #87 regression: the previous window fragments one sentence."""
    rows = _replay_turns(650)
    assert len(rows) == len(DELTAS) > 1
    assert rows != [GROUND_TRUTH]


def test_contract_split_counter_reports_zero_for_ordinary_pauses():
    pauses = [pause for _delta, pause in DELTAS]
    assert c.count_utterance_splits(pauses) == 0
    # The old 650ms window would have split on every pause >= 650ms.
    assert c.count_utterance_splits(pauses, vad_silence_ms=650) == 4


def test_a_genuine_end_of_thought_is_still_allowed_to_split():
    """A real pause longer than the window must still close the turn."""
    assert c.live_turn_boundary_reached(c.GEMINI_LIVE_VAD_SILENCE_MS) is True
    assert c.count_utterance_splits([c.GEMINI_LIVE_VAD_SILENCE_MS + 1]) == 1


def test_cumulative_hypotheses_do_not_duplicate_the_row():
    """A backend emitting cumulative hypotheses must still yield one clean row."""
    buffer = c.TranscriptTurnBuffer()
    buffer.merge("Could you tell me which bus goes to the central station")
    buffer.merge(
        "Could you tell me which bus goes to the central station "
        "and whether I need to transfer somewhere in the middle"
    )
    assert buffer.finish_turn() == (
        "Could you tell me which bus goes to the central station "
        "and whether I need to transfer somewhere in the middle"
    )


def test_tail_flush_recovers_the_final_clause_on_stream_stop():
    """#87 measurement: stopping with no signal lost the last clause."""
    settled: list[str | None] = []
    stream_end_calls: list[bool] = []
    flush = c.LiveTailFlush(
        on_settled=settled.append,
        send_audio_stream_end=lambda: stream_end_calls.append(True),
        set_timer=lambda _cb, _ms: object(),
        clear_timer=lambda _t: None,
    )
    assert stream_end_calls == [True]
    flush.accept("if there is another route that avoids them")
    flush.accept(None, finished=True)
    assert settled == ["if there is another route that avoids them"]


def test_handoff_buffer_keeps_a_sentence_across_a_session_rotation():
    """Audio captured during a rotation is replayed into the new session."""
    handoff = c.AudioHandoffBuffer(max_frames=c.LIVE_AUDIO_HANDOFF_FRAMES)
    handoff.start()
    frames = [b"frame-%d" % i for i in range(10)]
    for frame in frames:
        assert handoff.push(frame) is True
    assert handoff.dropped_frames == 0
    # The new session replays every frame in arrival order.
    assert handoff.release() == frames


def test_handoff_overflow_is_counted_not_silent():
    handoff = c.AudioHandoffBuffer(max_frames=3)
    handoff.start()
    for i in range(5):
        handoff.push(b"%d" % i)
    assert handoff.size == 3
    assert handoff.dropped_frames == 2


def test_groq_fallback_never_clips_a_long_sentence_mid_word():
    """Model the Groq cycle: chunks close at real pauses, not a fixed clock."""
    chunk_ms = 200  # a 200ms frame
    min_ms, silence_cut, max_ms = (
        c.GROQ_MIN_CHUNK_MS,
        c.GROQ_SILENCE_CUT_MS,
        c.GROQ_MAX_CHUNK_MS,
    )
    # Speech segments (ms) with the silence that follows each.
    timeline = [(6_000, 0), (2_000, 900), (3_000, 1_000), (4_000, 0)]
    chunks: list[str] = []
    elapsed = 0
    silence = 0
    for speech_ms, trailing_silence_ms in timeline:
        remaining = speech_ms
        while remaining > 0:
            step = min(chunk_ms, remaining)
            remaining -= step
            elapsed += step
            silence = 0
            if c.should_cut_groq_chunk(elapsed, silence):
                chunks.append("chunk")
                elapsed = 0
        silence = trailing_silence_ms
        elapsed += trailing_silence_ms
        if c.should_cut_groq_chunk(elapsed, silence):
            chunks.append("chunk")
            elapsed = 0
    # The old fixed 5500ms clock would have produced ~4 mid-sentence cuts; a
    # pause-aware cycle produces a small number of complete chunks.
    assert len(chunks) <= 4
    assert elapsed < max_ms
    assert min_ms < max_ms and silence_cut < min_ms


def test_no_fixed_clock_cut_when_speech_never_pauses():
    """Continuous speech is only cut by the bounded maximum, never at 5500ms."""
    assert c.should_cut_groq_chunk(elapsed_ms=5_500, silence_ms=0) is False
    assert c.should_cut_groq_chunk(elapsed_ms=10_000, silence_ms=0) is False
    assert c.should_cut_groq_chunk(elapsed_ms=c.GROQ_MAX_CHUNK_MS, silence_ms=0) is True


def test_end_to_end_no_duplicate_final_across_fallback_switch():
    """One utterance -> exactly one authoritative row even after a fallback."""
    deduper = c.TranscriptDeduper()
    utterance = c.make_utterance_id("sess-voice", 0, 0)
    rows: list[str] = []

    # Gemini Live goes down mid-utterance; the browser fallback finalises it.
    browser_final = c.TranscriptEvent(
        utterance, c.TranscriptKind.FINAL, GROUND_TRUTH, c.SttProvider.BROWSER_SPEECH
    )
    if deduper.accept(browser_final):
        rows.append(browser_final.text)
    # Groq Whisper then re-finalises the same utterance under the same id.
    groq_final = c.TranscriptEvent(
        utterance, c.TranscriptKind.FINAL, GROUND_TRUTH, c.SttProvider.GROQ_WHISPER
    )
    if deduper.accept(groq_final):
        rows.append(groq_final.text)

    assert rows == [GROUND_TRUTH]


def test_long_utterance_is_submitted_exactly_once_after_fallback():
    """Dedup (row) and submission guard (send) together prevent double submit."""
    deduper = c.TranscriptDeduper()
    guard = c.UtteranceSubmissionGuard()
    utterance = c.make_utterance_id("sess-voice", 0, 0)
    submissions: list[str] = []

    def submit(event: c.TranscriptEvent) -> None:
        if not deduper.accept(event):
            return
        if not guard.claim(event.utterance_id):
            return
        submissions.append(event.text)

    submit(c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, GROUND_TRUTH, c.SttProvider.BROWSER_SPEECH))
    # Groq re-finalises the same utterance; a replayed Send must be a no-op.
    submit(c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, GROUND_TRUTH, c.SttProvider.GROQ_WHISPER))
    submit(c.TranscriptEvent(utterance, c.TranscriptKind.FINAL, GROUND_TRUTH, c.SttProvider.GROQ_WHISPER))

    assert submissions == [GROUND_TRUTH]
