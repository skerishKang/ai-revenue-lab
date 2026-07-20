"""Tests for deterministic input normalization and segmentation."""

import unicodedata

import pytest

from app.domain.models import InputSegment
from app.pipeline.errors import SegmentationError
from app.pipeline.segmentation import (
    MAX_SEGMENTS,
    normalize_text,
    segment_text,
    verify_segments,
)


class TestNormalizeText:
    def test_normalize_empty_raises(self):
        with pytest.raises(SegmentationError, match="empty after normalization"):
            normalize_text("")

    def test_normalize_whitespace_only_raises(self):
        with pytest.raises(SegmentationError, match="empty after normalization"):
            normalize_text("   \n  \t  ")

    def test_non_string_raises(self):
        with pytest.raises(SegmentationError, match="must be a string"):
            normalize_text(123)

    def test_nfkc_normalization(self):
        raw = "\u2161"  # Roman numeral II
        result = normalize_text(raw)
        assert result == unicodedata.normalize("NFKC", raw)

    def test_crlf_to_lf(self):
        result = normalize_text("hello\r\nworld")
        assert result == "hello\nworld"

    def test_cr_to_lf(self):
        result = normalize_text("hello\rworld")
        assert result == "hello\nworld"

    def test_spaces_collapsed(self):
        result = normalize_text("hello    world")
        assert result == "hello world"

    def test_tabs_replaced(self):
        result = normalize_text("hello\t\tworld")
        assert result == "hello world"

    def test_trailing_whitespace_on_lines_trimmed(self):
        result = normalize_text("hello   \nworld  \nfoo")
        assert result == "hello\nworld\nfoo"

    def test_three_plus_newlines_collapsed(self):
        result = normalize_text("hello\n\n\n\nworld")
        assert result == "hello\n\nworld"

    def test_leading_and_trailing_whitespace_stripped(self):
        result = normalize_text("  hello world  ")
        assert result == "hello world"

    def test_preserves_single_newline(self):
        result = normalize_text("hello\nworld")
        assert result == "hello\nworld"

    def test_preserves_double_newline_paragraph_break(self):
        result = normalize_text("hello\n\nworld")
        assert result == "hello\n\nworld"

    def test_spaces_before_newline_dropped(self):
        result = normalize_text("hello   \nworld")
        assert result == "hello\nworld"

    def test_no_modification_of_clean_text(self):
        raw = "Hello world. This is clean text."
        assert normalize_text(raw) == raw


class TestSegmentText:
    def test_basic_korean_segmentation(self):
        text = "안녕하세요. 저는 개발자입니다. 반갑습니다."
        segments = segment_text(text)
        assert len(segments) >= 1
        segment_ids = [s.segment_id for s in segments]
        assert segment_ids[0] == "s001"

    def test_segment_ids_sequential(self):
        text = "A long text. With multiple sentences. That should span. Several segments. " * 10
        segments = segment_text(text, target_chars=100)
        assert len(segments) >= 2
        for i, seg in enumerate(segments):
            expected_id = f"s{i + 1:03d}"
            assert seg.segment_id == expected_id, f"Expected {expected_id}, got {seg.segment_id}"

    def test_offsets_are_contiguous_and_exact(self):
        text = "First sentence. Second sentence. Third sentence."
        segments = segment_text(text)
        normalized = normalize_text(text)
        verify_segments(normalized, segments)

    def test_single_sentence_segment(self):
        text = "Just one sentence here."
        segments = segment_text(text)
        assert len(segments) == 1
        assert segments[0].segment_id == "s001"

    def test_long_sentence_forms_own_segment(self):
        long_sentence = "Word " * 200 + "."
        text = f"{long_sentence} Short sentence."
        segments = segment_text(text, target_chars=100)
        assert len(segments) >= 2

    def test_empty_input_raises(self):
        with pytest.raises(SegmentationError):
            segment_text("")

    def test_invalid_target_chars_raises(self):
        with pytest.raises(SegmentationError, match="positive integer"):
            segment_text("hello", target_chars=0)

    def test_negative_target_chars_raises(self):
        with pytest.raises(SegmentationError, match="positive integer"):
            segment_text("hello", target_chars=-5)

    @pytest.mark.parametrize("target_chars", [10, 100, 480, 1000])
    def test_different_target_sizes(self, target_chars):
        text = "A. B. C. D. E. F. G. H. I. J. " * 5
        segments = segment_text(text, target_chars=target_chars)
        assert len(segments) >= 1
        normalized = normalize_text(text)
        verify_segments(normalized, segments)

    def test_custom_target_chars_produces_more_segments(self):
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. " * 5
        few = segment_text(text, target_chars=500)
        many = segment_text(text, target_chars=50)
        assert len(many) >= len(few)

    def test_korean_text_from_fixture(self):
        text = "처음에는 빠른 배송이 핵심 경쟁력이라고 생각했습니다. 모든 문제를 속도로 해결하려 했습니다."
        segments = segment_text(text)
        assert len(segments) >= 1
        assert all(
            isinstance(s.start_offset, int) and isinstance(s.end_offset, int)
            for s in segments
        )

    def test_preserves_paragraph_break(self):
        text = "First paragraph.\n\nSecond paragraph."
        segments = segment_text(text)
        normalized = normalize_text(text)
        verify_segments(normalized, segments)

    def test_max_segments_exceeded_raises(self):
        many_sentences = "Short sentence. " * (MAX_SEGMENTS * 10)
        with pytest.raises(SegmentationError, match="maximum is 32"):
            segment_text(many_sentences, target_chars=1)


class TestVerifySegments:
    def test_empty_segments_raises(self):
        with pytest.raises(SegmentationError, match="non-empty"):
            verify_segments("text", [])

    def test_first_segment_not_at_zero_raises(self):
        segs = [
            InputSegment(segment_id="s001", text="test", start_offset=5, end_offset=9),
        ]
        with pytest.raises(SegmentationError, match="must start at offset 0"):
            verify_segments("hello world test", segs)

    def test_duplicate_segment_id_raises(self):
        segs = [
            InputSegment(segment_id="s001", text="hello", start_offset=0, end_offset=5),
            InputSegment(segment_id="s001", text=" world", start_offset=5, end_offset=11),
        ]
        with pytest.raises(SegmentationError, match="duplicate"):
            verify_segments("hello world", segs)

    def test_gap_between_segments_raises(self):
        segs = [
            InputSegment(segment_id="s001", text="hello", start_offset=0, end_offset=5),
            InputSegment(segment_id="s002", text="world", start_offset=7, end_offset=12),
        ]
        with pytest.raises(SegmentationError, match="gap or overlap"):
            verify_segments("hello  world", segs)

    def test_text_mismatch_raises(self):
        segs = [
            InputSegment(segment_id="s001", text="wrong", start_offset=0, end_offset=5),
        ]
        with pytest.raises(SegmentationError, match="does not match"):
            verify_segments("hello", segs)

    def test_incomplete_coverage_raises(self):
        segs = [
            InputSegment(segment_id="s001", text="hello", start_offset=0, end_offset=5),
        ]
        with pytest.raises(SegmentationError, match="do not cover"):
            verify_segments("hello world", segs)

    def test_valid_segments_passes(self):
        segs = [
            InputSegment(segment_id="s001", text="hello", start_offset=0, end_offset=5),
            InputSegment(segment_id="s002", text=" world", start_offset=5, end_offset=11),
        ]
        verify_segments("hello world", segs)
