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


def test_code_first_requires_real_transition():
    # Original explanation-first -> adapted code-first: success.
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}])
    adapted = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "내용", "includes_code": True, "code_snippet": "x=1"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, ["code_first"])
    assert not any("code_first" in r for r in reasons)


def test_code_first_already_code_first_fails():
    # Original already code-first; adapted also code-first + unrelated change: fail.
    code_sect = [{"section_id": "s1", "title": "섹션", "content": "내용", "includes_code": True, "code_snippet": "x=1"}]
    orig = _content(sections=code_sect)
    adapted = _content(sections=code_sect, review_questions=[{"question": "q1"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, ["code_first"])
    assert any("code_first" in r for r in reasons)


def test_code_first_only_code_examples_list_fails():
    # Adapted has a code_examples list but the first section is explanation-first:
    # the code_examples list does not prove section rendering order.
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}])
    adapted = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}],
        code_examples=[{"example_id": "e1", "code": "x=1"}],
    )
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, ["code_first"])
    assert any("code_first" in r for r in reasons)


def test_simplify_jargon_term_definitions_increase():
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어"}])
    # term_definitions count increased (no reliance on the string "정의").
    with_terms = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어"}],
    )
    with_terms["term_definitions"] = [{"term": "변수", "definition": "값을 담는 이름"}]
    reasons = validate_material_adaptation(_plan(), orig, _plan(), with_terms, ["simplify_jargon"])
    assert not any("simplify_jargon" in r for r in reasons)


def test_simplify_jargon_string_definition_alone_fails():
    # Adding the string "정의" without reducing jargon or adding term_definitions
    # is NOT enough.
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어"}])
    with_str = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어 정의"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), with_str, ["simplify_jargon"])
    assert any("simplify_jargon" in r for r in reasons)


def test_simplify_jargon_jargon_decrease():
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "복잡한 개념 이론 용어"}])
    simpler = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "쉬운 설명"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), simpler, ["simplify_jargon"])
    assert not any("simplify_jargon" in r for r in reasons)


def test_multiple_directions_all_must_apply():
    # more_examples + code_first both requested.
    orig = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}],
        code_examples=[{"example_id": "e1", "code": "x=1"}],
    )
    # Both applied: example increased AND code-first transition.
    both = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "내용", "includes_code": True, "code_snippet": "x=1"}],
        code_examples=[{"example_id": "e1", "code": "x=1"}, {"example_id": "e2", "code": "y=2"}],
    )
    reasons = validate_material_adaptation(_plan(), orig, _plan(), both, ["more_examples", "code_first"])
    assert not any("more_examples" in r for r in reasons)
    assert not any("code_first" in r for r in reasons)


def test_multiple_directions_only_one_applied_fails():
    orig = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}],
        code_examples=[{"example_id": "e1", "code": "x=1"}],
    )
    # Only more_examples applied (example increased), code_first NOT applied.
    only_examples = _content(
        sections=[{"section_id": "s1", "title": "섹션", "content": "내용"}],
        code_examples=[{"example_id": "e1", "code": "x=1"}, {"example_id": "e2", "code": "y=2"}],
    )
    reasons = validate_material_adaptation(_plan(), orig, _plan(), only_examples, ["more_examples", "code_first"])
    assert not any("more_examples" in r for r in reasons)
    assert any("code_first" in r for r in reasons)


def test_reduce_theory_requires_theory_decrease_or_practice_increase():
    orig = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "긴 이론 설명 " * 10}])
    # Theory decreased.
    shorter = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "짧은"}])
    reasons = validate_material_adaptation(_plan(), orig, _plan(), shorter, ["reduce_theory"])
    assert not any("reduce_theory" in r for r in reasons)
    # Neither decreased theory nor increased practice -> fail.
    same = _content(sections=[{"section_id": "s1", "title": "섹션", "content": "긴 이론 설명 " * 10}])
    assert any("reduce_theory" in r for r in validate_material_adaptation(_plan(), orig, _plan(), same, ["reduce_theory"]))


def test_empty_directions_fails():
    orig = _content()
    adapted = _content(code_examples=[{"example_id": "e1", "code": "x=1"}])
    # A second lesson cannot be materially adapted without explicit feedback.
    reasons = validate_material_adaptation(_plan(), orig, _plan(), adapted, [])
    assert any("missing feedback directions" in r for r in reasons)
