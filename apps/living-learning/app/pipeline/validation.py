"""Lesson-content validation: safety, grounding, and adaptation materiality.

Grounding contract (Issue #37 blocker G): a review question's expected answer
must be justified *only* by material actually taught in the lesson — section
explanations, code examples, expected code output, or explicitly stated concept
facts. The question's own text, correct answer, and rationale are NOT valid
grounding evidence. If those fields are removed, the answer must still be
justifiable from the lesson body.
"""

from __future__ import annotations

import re

from app.pipeline.code_safety import validate_code_output

UNSAFE_PATTERNS = [
    (r"import\s+(?:os|sys|subprocess|requests|urllib|socket|pathlib|shutil)", "unsafe_module_import"),
    (r"\beval\s*\(", "eval"),
    (r"\bexec\s*\(", "exec"),
    (r"os\.system", "os.system"),
    (r"pip\s+install", "pip install"),
    (r"shell=True", "shell=True"),
    (r"\bopen\s*\(", "file_system_access"),
    (r"__import__", "dunder_import"),
]

CREDENTIAL_PATTERNS = [
    (r"input\s*\(\s*['\"].*(?:api[_-]?key|password|secret|token|credential).*['\"]\s*\)", "credential_collection"),
    (r"os\.environ(?:\[|\.get\()\s*['\"](?:API_KEY|PASSWORD|SECRET|TOKEN)['\"]", "credential_harvesting"),
]

HTML_SCRIPT_PATTERNS = [
    (r"<\s*script", "script tag"),
    (r"<\s*iframe", "iframe tag"),
    (r"on\w+\s*=", "event handler"),
    (r"javascript:", "javascript protocol"),
    (r"<\s*div[^>]*>", "div tag"),
    (r"<\s*a\s+href[^>]*>", "a tag"),
]

FABRICATED_FACTS_PATTERNS = [
    (r"(학습자님은|당신은|여러분은).*(앓고|장애|진단|우울|불안|ADHD|자폐|난독증)", "fabricated_medical_or_personal_fact"),
]


def validate_safe_content(content: str) -> list[str]:
    """Regex pre-screen for unsafe code, credential requests, markup, fabrications."""
    issues: list[str] = []
    for pattern, name in UNSAFE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"unsafe_code: {name}")
    for pattern, name in CREDENTIAL_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"credential_request: {name}")
    for pattern, name in HTML_SCRIPT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"markup_injection: {name}")
    for pattern, name in FABRICATED_FACTS_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"fabricated_facts: {name}")
    return issues


def _taught_evidence_corpus(content_payload: dict) -> str:
    """Build the corpus of legitimately-taught material for grounding.

    Deliberately EXCLUDES review_questions (question, correct_answer,
    explanation): an answer cannot be grounded in the very field it is supposed
    to justify. Only section prose/code and code examples count.
    """
    parts: list[str] = []
    for section in content_payload.get("sections", []) or []:
        parts.append(str(section.get("title", "")))
        parts.append(str(section.get("content", "")))
        if section.get("code_snippet"):
            parts.append(str(section.get("code_snippet", "")))
    for example in content_payload.get("code_examples", []) or []:
        parts.append(str(example.get("code", "")))
        parts.append(str(example.get("explanation", "")))
        parts.append(str(example.get("expected_output", "")))
    # Term definitions are explicitly taught concept facts.
    for term in content_payload.get("term_definitions", []) or []:
        if isinstance(term, dict):
            parts.append(str(term.get("term", "")))
            parts.append(str(term.get("definition", "")))
        else:
            parts.append(str(term))
    return "\n".join(parts)


def is_answer_grounded(answer: str, content_payload: dict) -> bool:
    """True if ``answer`` is justified by taught material only.

    An empty answer is considered trivially grounded (nothing to justify).
    """
    answer = (answer or "").strip()
    if not answer:
        return True
    corpus = _taught_evidence_corpus(content_payload)
    return answer in corpus


def validate_code_examples(content_payload: dict) -> list[str]:
    """Validate every code example and inline section snippet with the AST allowlist."""
    issues: list[str] = []
    for example in content_payload.get("code_examples", []) or []:
        code = example.get("code", "")
        expected = example.get("expected_output", "")
        if code and not validate_code_output(code, expected):
            issues.append("inconsistent_code_output")
    # Section inline snippets must also pass the allowlist (CTO finding #5).
    for section in content_payload.get("sections", []) or []:
        snippet = section.get("code_snippet", "")
        if section.get("includes_code") and snippet:
            if not validate_code_output(snippet, ""):
                issues.append("unsafe_section_code_snippet")
    return issues


def validate_section_alignment(plan_payload: dict, content_payload: dict) -> list[str]:
    plan_ids = {s.get("section_id") for s in plan_payload.get("sections", []) or []}
    content_ids = {s.get("section_id") for s in content_payload.get("sections", []) or []}
    if plan_ids != content_ids:
        return ["section_alignment_failure"]
    return []


def validate_review_answers(content_payload: dict) -> list[str]:
    issues: list[str] = []
    for question in content_payload.get("review_questions", []) or []:
        if not isinstance(question, dict):
            continue
        answer = question.get("correct_answer", "")
        if answer and not is_answer_grounded(answer, content_payload):
            issues.append("unsupported_review_answer")
    return issues


def validate_lesson_content(content_payload: dict, plan_payload: dict) -> list[str]:
    """Full structural validation of a generated lesson content payload."""
    import json

    issues = validate_safe_content(json.dumps(content_payload, ensure_ascii=False))
    issues += validate_section_alignment(plan_payload, content_payload)
    issues += validate_code_examples(content_payload)
    issues += validate_review_answers(content_payload)
    # De-duplicate preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique.append(issue)
    return unique


def validate_material_adaptation(
    original_plan: dict,
    original_content: dict,
    adapted_plan: dict,
    adapted_content: dict,
    direction_choices: set[str] | list[str],
) -> list[str]:
    """Canonical feedback-specific adaptation materiality check.

    Returns a list of failure reasons (empty == material). This is the single
    source of truth used both during second-lesson generation validation and
    during operator publication validation, so the two can never diverge.

    A change is material only if the requested feedback directions produced real
    structural changes — not merely a title/metadata/adaptation-note edit.
    """
    directions = set(direction_choices)
    error_reasons: list[str] = []

    def extract_core(plan: dict, content: dict) -> dict:
        return {
            "plan_sections": [s.get("section_id") for s in plan.get("sections", [])],
            "content_sections": [
                {k: v for k, v in s.items() if k != "title"}
                for s in content.get("sections", [])
            ],
            "review_questions": content.get("review_questions", []),
            "code_examples": content.get("code_examples", []),
        }

    if extract_core(original_plan, original_content) == extract_core(adapted_plan, adapted_content):
        error_reasons.append("metadata-only changes")

    orig_sections = original_content.get("sections", []) or []
    adapt_sections = adapted_content.get("sections", []) or []

    if "reduce_theory" in directions:
        orig_theory = sum(len(str(s)) for s in orig_sections)
        adapt_theory = sum(len(str(s)) for s in adapt_sections)
        orig_prac = len(original_content.get("code_examples", [])) + len(original_content.get("review_questions", []))
        adapt_prac = len(adapted_content.get("code_examples", [])) + len(adapted_content.get("review_questions", []))
        if not (adapt_theory < orig_theory or adapt_prac > orig_prac):
            error_reasons.append("reduce_theory: theory did not decrease and practice did not increase")

    if "more_examples" in directions:
        if len(adapted_content.get("code_examples", [])) <= len(original_content.get("code_examples", [])):
            error_reasons.append("more_examples: code_examples did not increase")

    if "code_first" in directions:
        first_sect = adapt_sections[0] if adapt_sections else {}
        has_code = first_sect.get("includes_code") and first_sect.get("code_snippet")
        if not has_code:
            code_examples = adapted_content.get("code_examples") or []
            first_ex = code_examples[0] if code_examples else {}
            if not first_ex.get("code"):
                error_reasons.append("code_first: first section has no code and first example is not code")

    if "slower_pace" in directions:
        orig_avg = sum(len(str(s)) for s in orig_sections) / max(1, len(orig_sections))
        adapt_avg = sum(len(str(s)) for s in adapt_sections) / max(1, len(adapt_sections))
        if adapt_avg >= orig_avg and len(adapt_sections) <= len(orig_sections):
            error_reasons.append("slower_pace: granularity did not increase and length did not decrease")

    if "more_review" in directions:
        if len(adapted_content.get("review_questions", [])) <= len(original_content.get("review_questions", [])):
            error_reasons.append("more_review: review_questions did not increase")

    if "simplify_jargon" in directions:
        orig_str = str(original_content).lower()
        adapt_str = str(adapted_content).lower()
        markers = ["복잡한", "용어", "개념", "이론"]
        orig_jargon = sum(orig_str.count(m) for m in markers)
        adapt_jargon = sum(adapt_str.count(m) for m in markers)
        if adapt_jargon >= orig_jargon and "정의" not in adapt_str:
            error_reasons.append("simplify_jargon: jargon did not decrease and no definitions added")

    return error_reasons
