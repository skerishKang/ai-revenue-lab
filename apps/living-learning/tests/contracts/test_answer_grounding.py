"""Blocker G: expected-answer grounding.

A review question's correct answer must be justified by material actually taught
— section prose, code examples, expected code output, or explicit term
definitions. The question's own text, correct answer, and rationale are NOT
valid grounding evidence.
"""

from __future__ import annotations

from app.pipeline.validation import is_answer_grounded, validate_review_answers


def test_answer_grounded_in_section_content():
    payload = {
        "sections": [{"section_id": "s1", "title": "변수", "content": "변수는 값을 담아 두는 이름입니다"}],
        "review_questions": [
            {"question": "변수란?", "correct_answer": "값을 담아 두는 이름", "explanation": "정의"}
        ],
    }
    assert is_answer_grounded("값을 담아 두는 이름", payload)


def test_answer_not_grounded_in_its_own_explanation():
    # The answer string appears ONLY in the review question's explanation —
    # which is not valid evidence.
    payload = {
        "sections": [{"section_id": "s1", "title": "t", "content": "unrelated content"}],
        "review_questions": [
            {"question": "q", "correct_answer": "magic_answer", "explanation": "because magic_answer"}
        ],
    }
    assert not is_answer_grounded("magic_answer", payload)


def test_answer_not_grounded_in_question_text():
    payload = {
        "sections": [{"section_id": "s1", "title": "t", "content": "unrelated"}],
        "review_questions": [
            {"question": "is magic_answer correct?", "correct_answer": "magic_answer", "explanation": "e"}
        ],
    }
    assert not is_answer_grounded("magic_answer", payload)


def test_answer_grounded_in_code_expected_output():
    payload = {
        "sections": [{"section_id": "s1", "title": "t", "content": "unrelated"}],
        "code_examples": [
            {"example_id": "e1", "code": "print(42)", "expected_output": "42", "explanation": "출력"}
        ],
        "review_questions": [{"question": "출력은?", "correct_answer": "42", "explanation": "e"}],
    }
    assert is_answer_grounded("42", payload)


def test_answer_grounded_in_term_definition():
    payload = {
        "sections": [{"section_id": "s1", "title": "t", "content": "unrelated"}],
        "term_definitions": [{"term": "문자열", "definition": "따옴표로 감싼 글자"}],
        "review_questions": [
            {"question": "문자열이란?", "correct_answer": "따옴표로 감싼 글자", "explanation": "e"}
        ],
    }
    assert is_answer_grounded("따옴표로 감싼 글자", payload)


def test_validate_review_answers_flags_ungrounded():
    payload = {
        "sections": [{"section_id": "s1", "title": "t", "content": "unrelated"}],
        "review_questions": [
            {"question": "q", "correct_answer": "ungrounded", "explanation": "ungrounded"}
        ],
    }
    issues = validate_review_answers(payload)
    assert "unsupported_review_answer" in issues


def test_empty_answer_is_trivially_grounded():
    assert is_answer_grounded("", {"sections": []})
