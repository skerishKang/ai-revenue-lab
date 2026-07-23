"""P1: canonical adaptation materiality validator.

The single source of truth used by both second-lesson generation validation and
operator publication validation. A change is material only if the requested
feedback directions produced real structural changes — not merely a title,
metadata, or adaptation-note edit.
"""

from __future__ import annotations

from app.pipeline.validation import validate_material_adaptation


def _content(sections=None, code_examples=None, review_questions=None):
    return {
        "title": "t",
        "sections": sections if sections is not None else [{"section_id": "s1", "title": "섹션", "content": "내용"}],
        "code_examples": code_examples if code_examples is not None else [],
        "review_questions": review_questions if review_questions is not None else [],
    }


def _plan(sections=None):
    return {"title": "p", "sections": sections if sections is not None else [{"section_id": "s1", "title": "섹션"}]}


def test_metadata_only_change_fails():
    orig = _content()
    # Only title / adaptation notes differ — core unchanged.
    adapted = _content()
    adapted["title"] = "다른 제목"
    adapted["adaptation_notes"] = "바뀜"
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, ["more_examples"])
    assert any("metadata-only" in r for r in reasons)


def test_more_examples_requires_actual_increase():
    orig = _content(code_examples=[{"example_id": "e1", "code": "x=1"}])
    # No increase -> fail.
    same = _content(code_examples=[{"example_id": "e1", "code": "x=1"}])
    assert validate_material_adaptation(_plan(), orig, _plan(), same, ["more_examples"])
    # Increase -> pass (no more_examples reason).
    more = _content(code_examples=[{"example_id": "e1", "code": "x=1"}, {"example_id": "e2", "code": "y=2"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), more, ["more_examples"])
    assert not any("more_examples" in r for r in reasons)


def test_more_review_requires_actual_increase():
    orig = _content(review_questions=[{"question": "q1"}])
    same = _content(review_questions=[{"question": "q1"}])
    assert any("more_review" in r for r in validate_material_adaptation(_plan(), orig, _plan(), same, ["more_review"]))
    more = _content(review_questions=[{"question": "q1"}, {"question": "q2"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), more, ["more_review"])
    assert not any("more_review" in r for r in reasons)


def test_code_first_requires_code_before_explanation():
    orig = _content()
    # Adapted first section has code first.
    adapted = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "내용", "includes_code": True, "code_snippet": "x=1"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, ["code_first"])
    assert not any("code_first" in r for r in reasons)
    # No code first -> fail.
    no_code = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}])
    assert any("code_first" in r for r in validate_material_adaptation(_plan(), orig, _plan(), no_code, ["code_first"]))


def test_reduce_theory_requires_theory_decrease_or_practice_increase():
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "긴 이론 설명 " * 10}])
    # Theory decreased.
    shorter = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "짧은"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), shorter, ["reduce_theory"])
    assert not any("reduce_theory" in r for r in reasons)
    # Neither decreased theory nor increased practice -> fail.
    same = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "긴 이론 설명 " * 10}])
    assert any("reduce_theory" in r for r in validate_material_adaptation(_plan(), orig, _plan(), same, ["reduce_theory"]))


def test_simplify_jargon_requires_jargon_decrease_or_definition():
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어"}])
    # Definition added.
    with_def = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어 정의: 쉬움"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), with_def, ["simplify_jargon"])
    assert not any("simplify_jargon" in r for r in reasons)


def test_empty_directions_only_metadata_check():
    orig = _content()
    adapted = _content(code_examples=[{"example_id": "e1", "code": "x=1"}])
    # No directions requested: only the metadata-only core check applies; core
    # changed (code_examples added) so it is not metadata-only.
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, [])
    assert reasons == []
