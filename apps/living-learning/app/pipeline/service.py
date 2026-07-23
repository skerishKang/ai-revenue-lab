"""Living Learning pipeline service with proper atomicity and staging."""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.models import (
    LessonContent,
    LessonPlan,
    ProviderResult,
)
from app.repositories import (
    claim_idempotency_request,
    close_lesson,
    create_curriculum,
    create_exercise,
    create_feedback,
    create_generation_run,
    create_learner,
    create_lesson,
    create_learner_session,
    create_pilot_evidence,
    get_concept_by_id,
    get_exercise_by_id,
    get_feedback_by_id,
    get_learner_by_id,
    get_lesson_by_id,
    get_lessons_by_learner,
    is_feedback_applied,
    is_feedback_for_learner,
    mark_feedback_applied,
    record_comprehension_response,
    record_exercise_response,
    complete_idempotency_request,
    sum_tokens_by_lesson,
    update_lesson_status,
    upsert_mastery,
    validate_prerequisites,
)
from app.pipeline.errors import (
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    PrerequisiteNotMetError,
    RetryExhaustedError,
    ContentValidationError,
    AdaptationNotChangedError,
    ComprehensionRequiredError,
    LearnerInactiveError,
    UnsafeContentError,
    NonRetryableError,
)
from app.pipeline.prompts import (
    ADAPTED_LESSON_CONTENT_PROMPT,
    ADAPTED_LESSON_PROMPT,
    LESSON_CONTENT_PROMPT,
    LESSON_PLAN_PROMPT,
)
from app.ai.base import AIProvider

if TYPE_CHECKING:
    pass

MAX_RETRIES = 3

RETRYABLE_ERROR_CATEGORIES = frozenset({
    "timeout",
    "rate_limit",
    "connection_error",
    "transient_provider_error",
})

NON_RETRYABLE_ERROR_CATEGORIES = frozenset({
    "authentication_error",
    "authorization_error",
    "provider_refusal",
    "unsafe_content",
    "invalid_request",
    "schema_mismatch",
})

UNSAFE_PATTERNS = [
    (r"import\s+(?:os|sys|subprocess|requests|urllib|socket|pathlib|shutil)", "unsafe_module_import"),
    (r"eval\s*\(", "eval"),
    (r"exec\s*\(", "exec"),
    (r"os\.system", "os.system"),
    (r"pip\s+install", "pip install"),
    (r"!.*curl", "curl"),
    (r"shell=True", "shell=True"),
    (r"open\s*\(", "file_system_access"),
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
    (r"<\s*b\s*>", "b tag"),
    (r"<\s*a\s+href[^>]*>", "a tag"),
]

FABRICATED_FACTS_PATTERNS = [
    (r"(학습자님은|당신은|여러분은).*(앓고|장애|진단|우울|불안|ADHD|자폐|난독증|살이|직업|이력|근무|경력)", "fabricated_medical_or_personal_fact"),
]

def _validate_safe_content(content: str) -> list[str]:
    issues = []
    content_lower = content.lower()

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


def _validate_code_output(code: str, expected: str) -> bool:
    import ast
    try:
        tree = ast.parse(code)
    except Exception:
        return False

    allowed_nodes = (ast.Module, ast.Assign, ast.Name, ast.Store, ast.Load, ast.Constant, ast.Expr, ast.Call, ast.If, ast.Compare, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div)
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            return False

    # Naive evaluation for simple assignments and prints
    env = {}
    output = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                val = stmt.value
                if isinstance(val, ast.Constant):
                    env[stmt.targets[0].id] = val.value
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Name) and call.func.id == "print":
                for arg in call.args:
                    if isinstance(arg, ast.Name) and arg.id in env:
                        output.append(str(env[arg.id]))
                    elif isinstance(arg, ast.Constant):
                        output.append(str(arg.value))
    
    simulated_output = " ".join(output)
    if simulated_output.strip() != expected.strip() and expected.strip():
        # strict check: if expected output is provided, it must match
        return False
    return True

def _is_retryable_error(error_category: str, is_exception: bool = False) -> bool:
    if is_exception:
        return True
    if error_category in RETRYABLE_ERROR_CATEGORIES:
        return True
    if error_category in NON_RETRYABLE_ERROR_CATEGORIES:
        return False
    return False


class LessonPipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: AIProvider,
        settings: Any = None,
    ) -> None:
        self.conn = conn
        self.provider = provider
        self.settings = settings or type("Settings", (), {
            "provider_type": "mock",
            "provider_model": "mock-fixture",
            "database_url": ":memory:",
        })()

    def _validate_learner_active(self, learner_id: str) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")
        if learner.status not in ("active",):
            raise LearnerInactiveError(learner_id, learner.status)


    def _execute_provider_task(
        self,
        task_name: str,
        lesson_id: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type,
        request_id_prefix: str,
        prompt_version: str = "",
        validator = None,
    ) -> ProviderResult:
        for attempt in range(MAX_RETRIES):
            req_id = f"{request_id_prefix}_{attempt}"
            import time
            start_time = time.perf_counter()
            try:
                res = self.provider.generate_structured(
                    task_name=task_name,
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                    request_id=req_id,
                )
                
                if res.success and validator:
                    issues = validator(res.payload)
                    if issues:
                        res.success = False
                        res.error_category = issues[0]
                        res.error_message = f"Validation failed: {issues}"

                if not res.success:
                    # Raise an exception that carries the error_category
                    exc = RuntimeError(res.error_category or "unknown_exception")
                    exc.error_category = res.error_category or "unknown_exception"
                    # Preserve usage
                    exc.res = res
                    raise exc
            except Exception as exc:
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                
                provider_type = getattr(self.provider, 'provider_type', getattr(self.settings, 'provider_type', 'mock'))
                advertised_model = getattr(self.provider, 'model', getattr(self.settings, 'provider_model', 'mock-fixture'))
                
                cost_class = "free"
                prompt_tokens = 0
                completion_tokens = 0

                if hasattr(exc, "res"):
                    res = exc.res
                    latency_ms = res.latency_ms
                    provider_type = res.provider
                    advertised_model = res.model
                    cost_class = res.cost_class
                    prompt_tokens = res.prompt_tokens
                    completion_tokens = res.completion_tokens

                if hasattr(exc, "error_category"):
                    error_category = exc.error_category
                    is_transient = _is_retryable_error(error_category)
                else:
                    is_transient = isinstance(exc, (TimeoutError, ConnectionError))
                    error_category = "transient_provider_error" if is_transient else "unknown_exception"

                create_generation_run(
                    self.conn,
                    task_type=task_name,
                    lesson_id=lesson_id,
                    success=False,
                    error_message=error_category,
                    provider=provider_type,
                    advertised_model=advertised_model,
                    cost_class=cost_class,
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    error_category=error_category,
                    attempt_number=attempt + 1,
                    request_id=req_id,
                )
                
                if not is_transient or attempt >= MAX_RETRIES - 1:
                    # Mark failure will be handled by caller now, we don't insert partial lessons
                    if is_transient:
                        raise RetryExhaustedError(task_name, attempt + 1) from exc
                    if error_category == "unsafe_content_policy_violation" or error_category.startswith(("unsafe_", "markup_", "credential_", "fabricated_")):
                        raise UnsafeContentError(error_category) from exc
                    raise NonRetryableError(error_category) from exc
                continue

            create_generation_run(
                self.conn,
                task_type=task_name,
                provider=res.provider,
                advertised_model=res.model,
                cost_class=res.cost_class,
                prompt_version=prompt_version,
                latency_ms=res.latency_ms,
                prompt_tokens=res.prompt_tokens,
                completion_tokens=res.completion_tokens,
                lesson_id=lesson_id,
                success=res.success,
                error_category=res.error_category if not res.success else "",
                error_message=res.error_message[:200] if res.error_message else "",
                attempt_number=attempt + 1,
                request_id=req_id,
            )

            if not res.success:
                if res.error_category in RETRYABLE_ERROR_CATEGORIES:
                    if attempt >= MAX_RETRIES - 1:
                        if lesson_id:
                            update_lesson_status(self.conn, lesson_id, "generation_failed", commit=False)
                        raise RetryExhaustedError(task_name, attempt + 1)
                    continue
                else:
                    if lesson_id:
                        update_lesson_status(self.conn, lesson_id, "generation_failed", commit=False)
                    raise NonRetryableError(f"{task_name} failed: {res.error_category}")
            
            return res
        
        if lesson_id:
            update_lesson_status(self.conn, lesson_id, "generation_failed", commit=False)
        raise GenerationError(f"Task {task_name} exhausted retries unexpectedly")

    def create_learner_and_session(self, topic: str, **preferences) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            learner = create_learner(self.conn, topic=topic, **preferences, commit=False)
            curriculum = create_curriculum(self.conn, topic=topic, commit=False)
            session_id = f"sess_{secrets.token_urlsafe(16)}"
            cursor.execute(
                "INSERT INTO learner_sessions (session_id, learner_id, curriculum_id, current_lesson_sequence, last_activity_at, created_at) VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))",
                (session_id, learner.id, curriculum.id),
            )
            concept_map = [
                ("variables", "변수", [], 0),
                ("values", "값", [], 1),
                ("conditionals", "간단한 조건문", ["variables", "values"], 2),
                ("python_example", "Python 예제", ["variables", "values", "conditionals"], 3),
            ]
            concept_ids = {}
            for eng_name, korean_name, prereqs, seq_order in concept_map:
                prereq_ids = [concept_ids[p] for p in prereqs if p in concept_ids]
                concept = self._create_concept_with_stable_id(
                    cursor, curriculum.id, eng_name, korean_name, prereq_ids, seq_order
                )
                concept_ids[eng_name] = concept.id
                upsert_mastery(self.conn, learner_id=learner.id, concept_id=concept.id, commit=False)
            self.conn.commit()
            return {"learner_id": learner.id, "session_id": session_id, "curriculum_id": curriculum.id}
        except Exception:
            self.conn.rollback()
            raise

    def _create_concept_with_stable_id(self, cursor: sqlite3.Cursor, curriculum_id: str, name: str, description: str, prerequisites: list[str], sequence_order: int) -> Any:
        import hashlib
        # curriculum_id + name_slug
        name_slug = name.strip().lower()
        key = f"{curriculum_id}:{name_slug}".encode("utf-8")
        concept_id = f"concept_{hashlib.md5(key).hexdigest()}"
        
        existing = cursor.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if existing:
            cursor.execute("UPDATE concepts SET prerequisites = ?, sequence_order = ? WHERE id = ?", (json.dumps(prerequisites), sequence_order, concept_id))
            return type('ConceptRecord', (), {'id': concept_id, 'curriculum_id': curriculum_id, 'name': name, 'description': description, 'prerequisites': prerequisites, 'sequence_order': sequence_order})()
        
        cursor.execute("INSERT INTO concepts (id, curriculum_id, name, description, prerequisites, sequence_order, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))", (concept_id, curriculum_id, name, description, json.dumps(prerequisites), sequence_order))
        return type('ConceptRecord', (), {'id': concept_id, 'curriculum_id': curriculum_id, 'name': name, 'description': description, 'prerequisites': prerequisites, 'sequence_order': sequence_order})()

    def start_first_lesson(self, learner_id: str, concept_id: str, idempotency_key: str = "") -> str:
        self._validate_learner_active(learner_id)
        
        # Check idempotency but with resource binding validation
        op_key = f"start_lesson:{learner_id}:{concept_id}:{idempotency_key}" if idempotency_key else ""
        if op_key:
            existing = claim_idempotency_request(self.conn, op_key)
            if existing is None:
                raise GenerationError("Concurrent request in progress")
            if existing.status == "completed":
                try:
                    res = json.loads(existing.result)
                    return res.get("lesson_id", existing.lesson_id)
                except Exception:
                    return existing.lesson_id

        valid, missing = validate_prerequisites(self.conn, concept_id, learner_id)
        if not valid:
            raise PrerequisiteNotMetError(concept_id, missing)
        
        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, concept_id)
        if not learner or not concept:
            raise GenerationError("Learner or concept not found")
            
        session = self.conn.execute("SELECT curriculum_id FROM learner_sessions WHERE learner_id = ? ORDER BY created_at DESC LIMIT 1", (learner_id,)).fetchone()
        if not session or session[0] != concept.curriculum_id:
            raise GenerationError(f"Concept {concept_id} does not belong to the learner's session curriculum.")
            
        candidate_id = f"lesson_{secrets.token_urlsafe(16)}"
        
        return self._generate_full_lesson_content(candidate_id, learner, concept, op_key)

    def _generate_full_lesson_content(self, lesson_id: str, learner, concept, idempotency_key: str = "") -> str:
        # 1. Prepare Plan Payload
        plan_user_payload = {
            "topic": learner.topic,
            "concept_name": concept.name,
            "example_preference": getattr(learner, 'example_preference', 'balanced'),
            "theory_density": getattr(learner, 'theory_density', 'standard'),
            "jargon_level": getattr(learner, 'jargon_level', 'standard'),
            "review_question_count": getattr(learner, 'review_question_count', 2),
        }
        plan_system_prompt = LESSON_PLAN_PROMPT.format(**plan_user_payload)
        
        def plan_validator(payload):
            plan_data = json.dumps(payload, ensure_ascii=False)
            if issues := _validate_safe_content(plan_data):
                return issues
            return []
            
        plan_result = self._execute_provider_task(
            task_name="lesson_plan", 
            lesson_id=lesson_id, 
            system_prompt=plan_system_prompt, 
            user_payload=plan_user_payload, 
            response_schema=LessonPlan, 
            request_id_prefix=f"plan_{lesson_id}",
            prompt_version="ll-plan-v1",
            validator=plan_validator
        )
        plan_payload = plan_result.payload
        plan_data = json.dumps(plan_payload, ensure_ascii=False)

        # 2. Prepare Content Payload
        content_user_payload = {
            "example_preference": plan_user_payload["example_preference"],
            "theory_density": plan_user_payload["theory_density"],
            "jargon_level": plan_user_payload["jargon_level"],
            "pacing_feedback_style": "standard",
            "lesson_plan": plan_data,
        }
        content_system_prompt = LESSON_CONTENT_PROMPT.format(**content_user_payload)
        
        def _check_grounding(ans, payload):
            if not ans: return True
            for s in payload.get("sections", []):
                if ans in str(s.get("content", "")): return True
            for ex in payload.get("code_examples", []):
                if ans in str(ex.get("expected_output", "")): return True
            for q in payload.get("review_questions", []):
                if ans in str(q.get("explanation", "")): return True
            return False

        def content_validator(payload):
            content_data = json.dumps(payload, ensure_ascii=False)
            issues = _validate_safe_content(content_data)
            plan_section_ids = {s.get("section_id") for s in plan_payload.get("sections", [])}
            content_section_ids = {s.get("section_id") for s in payload.get("sections", [])}
            if plan_section_ids != content_section_ids:
                issues.append("section_alignment_failure")
            if payload.get("code_examples"):
                for ex in payload["code_examples"]:
                    code = ex.get("code", "")
                    expected = ex.get("expected_output", "")
                    if code and not _validate_code_output(code, expected):
                        issues.append("inconsistent_code_output")
            if payload.get("review_questions"):
                for q in payload["review_questions"]:
                    ans = q.get("correct_answer", "") if isinstance(q, dict) else ""
                    if ans and not _check_grounding(ans, payload):
                        issues.append("unsupported_review_answer")
            return issues
            
        content_result = self._execute_provider_task(
            task_name="lesson_content", 
            lesson_id=lesson_id, 
            system_prompt=content_system_prompt, 
            user_payload=content_user_payload, 
            response_schema=LessonContent, 
            request_id_prefix=f"content_{lesson_id}",
            prompt_version="ll-content-v1",
            validator=content_validator
        )
        content_payload = content_result.payload
        content_data = json.dumps(content_payload, ensure_ascii=False)

        # 3. Persistence in a single IMMEDIATE transaction
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            create_lesson(
                self.conn, learner_id=learner.id, concept_id=concept.id, lesson_number=1, generation_status="pending_review", lesson_plan_json=plan_data, lesson_content_json=content_data, commit=False, id=lesson_id
            )
            
            if content_payload.get("code_examples"):
                for i, ex in enumerate(content_payload["code_examples"]):
                    create_exercise(self.conn, lesson_id=lesson_id, question=f"다음 코드의 출력은 무엇인가요?\n```{ex.get('language', 'python')}\n{ex.get('code', '')}```", options=[], correct_answer=ex.get("expected_output", ""), explanation=ex.get("explanation", ""), difficulty="easy", sequence_order=i, commit=False)
            if content_payload.get("review_questions"):
                base_seq = len(content_payload.get("code_examples", []))
                for i, q in enumerate(content_payload["review_questions"]):
                    create_exercise(self.conn, lesson_id=lesson_id, question=q.get("question", "") if isinstance(q, dict) else q, options=[], correct_answer=q.get("correct_answer", "") if isinstance(q, dict) else "", explanation=q.get("explanation", "") if isinstance(q, dict) else "", difficulty="medium", sequence_order=base_seq + i, commit=False)
            if idempotency_key:
                complete_idempotency_request(self.conn, idempotency_key, result=json.dumps({"lesson_id": lesson_id, "status": "complete"}), commit=False)
            self.conn.commit()
            return lesson_id
        except Exception:
            self.conn.rollback()
            if idempotency_key:
                try:
                    from app.repositories.idempotency_repository import fail_idempotency_request
                    fail_idempotency_request(self.conn, idempotency_key, commit=True)
                except Exception:
                    pass
            raise

    def record_comprehension(self, lesson_id: str, learner_id: str, understood: bool, difficulty_rating: int = 3, free_text: str = "") -> dict:
        self._validate_learner_active(learner_id)
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            resp = record_comprehension_response(self.conn, lesson_id=lesson_id, learner_id=learner_id, understood=understood, difficulty_rating=difficulty_rating, free_text=free_text, commit=False)
            cursor.execute("UPDATE lessons SET updated_at = datetime('now') WHERE id = ?", (lesson_id,))
            self.conn.commit()
            return {"response_id": resp.id, "success": True}
        except Exception:
            self.conn.rollback()
            raise

    def record_feedback(self, lesson_id: str, learner_id: str, direction_choices: list[str], free_text: str = "", idempotency_key: str = "") -> dict:
        self._validate_learner_active(learner_id)
        
        valid_directions = {"reduce_theory", "more_examples", "code_first", "slower_pace", "more_review", "simplify_jargon"}
        for d in direction_choices:
            if d not in valid_directions:
                raise GenerationError(f"Unknown feedback direction: {d}")
                
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)
        op_key = f"feedback:{lesson_id}:{learner_id}:{idempotency_key}" if idempotency_key else ""
        existing = claim_idempotency_request(self.conn, op_key) if op_key else None
        if existing:
            result = json.loads(existing.result) if existing.result else {}
            return {"feedback_id": result.get("feedback_id", ""), "is_duplicate": True}
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            feedback = create_feedback(self.conn, lesson_id=lesson_id, learner_id=learner_id, lesson_generation=lesson.lesson_number, direction_choices=direction_choices, free_text=free_text, commit=False)
            if op_key:
                complete_idempotency_request(self.conn, op_key, result=json.dumps({"feedback_id": feedback.id}), commit=False)
            self.conn.commit()
            return {"feedback_id": feedback.id, "is_duplicate": False}
        except Exception:
            self.conn.rollback()
            raise

    def process_feedback_and_generate_second_lesson(self, lesson_id: str, learner_id: str, comprehension_response_id: str, feedback_id: str, idempotency_key: str = "") -> dict:
        self._validate_learner_active(learner_id)
        
        op_key = f"second_lesson:{lesson_id}:{comprehension_response_id}:{feedback_id}:{idempotency_key}" if idempotency_key else ""
        if op_key:
            existing = claim_idempotency_request(self.conn, op_key)
            if existing is None:
                raise GenerationError("Concurrent request in progress")
            if existing.status == "completed":
                try:
                    res = json.loads(existing.result)
                    return {"lesson_id": res.get("lesson_id", existing.resource_id), "adaptation_verified": True}
                except Exception:
                    return {"lesson_id": existing.resource_id, "adaptation_verified": True}

        original_lesson = get_lesson_by_id(self.conn, lesson_id)
        if not original_lesson:
            raise GenerationError("Lesson not found")
        if original_lesson.generation_status not in ("pending_review", "published", "closed", "input_received"):
            raise GenerationError(f"Prior lesson is not in an explicitly accepted completed state: {original_lesson.generation_status}")
        if not original_lesson.lesson_plan_json or not original_lesson.lesson_content_json or original_lesson.lesson_plan_json == "{}" or original_lesson.lesson_content_json == "{}":
            raise GenerationError("Prior lesson is missing plan/content")

        feedback = get_feedback_by_id(self.conn, feedback_id)
        if not feedback:
            raise GenerationError("Feedback not found")
        if feedback.lesson_id != lesson_id:
            raise GenerationError("Feedback lesson_id mismatch")
        if feedback.learner_id != learner_id:
            raise ForeignFeedbackError(feedback_id, learner_id)
        if feedback.lesson_generation != original_lesson.lesson_number:
            raise GenerationError("Feedback generation mismatch")

        comprehension = self.conn.execute(
            "SELECT * FROM comprehension_responses WHERE id = ? AND lesson_id = ? AND learner_id = ?",
            (comprehension_response_id, lesson_id, learner_id),
        ).fetchone()
        if not comprehension:
            raise ComprehensionRequiredError("Comprehension response required for second lesson")

        if is_feedback_applied(self.conn, feedback_id):
            raise FeedbackAlreadyAppliedError(feedback_id)

        candidate_id = f"lesson_{secrets.token_urlsafe(16)}"
        
        lesson_id = self._generate_adapted_content(lesson_id=candidate_id, learner_id=learner_id, original_lesson=original_lesson, feedback=feedback, comprehension=comprehension, idempotency_key=op_key)
        return {"lesson_id": lesson_id, "adaptation_verified": True}

    def _generate_adapted_content(self, lesson_id: str, learner_id: str, original_lesson, feedback, comprehension, idempotency_key: str = "") -> str:
        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, original_lesson.concept_id)
        if not learner or not concept:
            raise GenerationError("Learner or concept not found")

        plan_data = json.loads(original_lesson.lesson_plan_json)
        content_data = json.loads(original_lesson.lesson_content_json)

        payload_kwargs = {
            "original_plan": json.dumps(plan_data, ensure_ascii=False),
            "original_content": json.dumps(content_data, ensure_ascii=False),
            "direction_choices": ", ".join(feedback.direction_choices),
            "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
            "comprehension_understood": str(bool(comprehension["understood"])),
            "comprehension_difficulty": str(comprehension["difficulty_rating"]),
            "comprehension_text": comprehension["free_text"] or ""
        }
        
        plan_system_prompt = ADAPTED_LESSON_PROMPT.format(**payload_kwargs)

        def plan_validator(payload):
            plan_data = json.dumps(payload, ensure_ascii=False)
            if issues := _validate_safe_content(plan_data):
                return issues
            return []
            
        adapted_plan_result = self._execute_provider_task(
            task_name="adapted_lesson_plan", 
            lesson_id=lesson_id, 
            system_prompt=plan_system_prompt, 
            user_payload=payload_kwargs, 
            response_schema=LessonPlan, 
            request_id_prefix=f"adapt_plan_{lesson_id}",
            prompt_version="ll-adapt-plan-v1",
            validator=plan_validator
        )
        adapted_payload = adapted_plan_result.payload
        adapted_data = json.dumps(adapted_payload, ensure_ascii=False)

        payload_kwargs["original_plan"] = adapted_data
        
        content_user_payload = {
            "example_preference": getattr(learner, 'example_preference', 'balanced'),
            "theory_density": getattr(learner, 'theory_density', 'standard'),
            "jargon_level": getattr(learner, 'jargon_level', 'standard'),
            "pacing_feedback_style": "adapted",
            "lesson_plan": adapted_data,
            "original_plan": json.dumps(plan_data, ensure_ascii=False),
            "original_content": json.dumps(content_data, ensure_ascii=False),
            "direction_choices": ", ".join(feedback.direction_choices),
            "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
            "comprehension_understood": str(bool(comprehension["understood"])),
            "comprehension_difficulty": str(comprehension["difficulty_rating"]),
            "comprehension_text": comprehension["free_text"] or ""
        }
        content_system_prompt = ADAPTED_LESSON_CONTENT_PROMPT.format(**content_user_payload)

        def _check_grounding(ans, payload):
            if not ans: return True
            for s in payload.get("sections", []):
                if ans in str(s.get("content", "")): return True
            for ex in payload.get("code_examples", []):
                if ans in str(ex.get("expected_output", "")): return True
            for q in payload.get("review_questions", []):
                if ans in str(q.get("explanation", "")): return True
            return False

        def content_validator(payload):
            final_content_data = json.dumps(payload, ensure_ascii=False)
            issues = _validate_safe_content(final_content_data)
            plan_section_ids = {s.get("section_id") for s in adapted_payload.get("sections", [])}
            content_section_ids = {s.get("section_id") for s in payload.get("sections", [])}
            if plan_section_ids != content_section_ids:
                issues.append("section_alignment_failure")
                
            if payload.get("code_examples"):
                for ex in payload["code_examples"]:
                    code = ex.get("code", "")
                    expected = ex.get("expected_output", "")
                    if code and not _validate_code_output(code, expected):
                        issues.append("inconsistent_code_output")
            if payload.get("review_questions"):
                for q in payload["review_questions"]:
                    ans = q.get("correct_answer", "") if isinstance(q, dict) else ""
                    if ans and not _check_grounding(ans, payload):
                        issues.append("unsupported_review_answer")
            
            # verification logic
            error_reasons = []
            direction_choices = set(feedback.direction_choices)
            
            def extract_core(plan: dict, content: dict) -> dict:
                return {
                    "plan_sections": [s.get("section_id") for s in plan.get("sections", [])],
                    "content_sections": [
                        {k: v for k, v in s.items() if k not in ("title",)}
                        for s in content.get("sections", [])
                    ],
                    "review_questions": content.get("review_questions", []),
                    "code_examples": content.get("code_examples", []),
                }

            orig_core = extract_core(plan_data, content_data)
            adapt_core = extract_core(adapted_payload, payload)

            if orig_core == adapt_core:
                error_reasons.append("metadata-only changes")

            if "reduce_theory" in direction_choices:
                orig_theory = sum(len(str(s)) for s in content_data.get("sections", []))
                adapt_theory = sum(len(str(s)) for s in payload.get("sections", []))
                orig_prac = len(content_data.get("code_examples", [])) + len(content_data.get("review_questions", []))
                adapt_prac = len(payload.get("code_examples", [])) + len(payload.get("review_questions", []))
                if not (adapt_theory < orig_theory or adapt_prac > orig_prac):
                    error_reasons.append("reduce_theory requested but theory didn't decrease and practical ratio didn't increase")

            if "more_examples" in direction_choices:
                orig_ex = len(content_data.get("code_examples", []))
                adapt_ex = len(payload.get("code_examples", []))
                if adapt_ex <= orig_ex:
                    error_reasons.append("more_examples requested but code_examples did not increase")

            if "code_first" in direction_choices:
                first_sect = payload.get("sections", [{}])[0] if payload.get("sections") else {}
                has_code = first_sect.get("includes_code") and first_sect.get("code_snippet")
                if not has_code:
                    code_examples = payload.get("code_examples") or []
                    first_ex = code_examples[0] if code_examples else {}
                    if not first_ex.get("code"):
                        error_reasons.append("code_first requested but first section does not include code snippet and first exercise is not code-based")

            if "slower_pace" in direction_choices:
                orig_avg = sum(len(str(s)) for s in content_data.get("sections", [])) / max(1, len(content_data.get("sections", [])))
                adapt_avg = sum(len(str(s)) for s in payload.get("sections", [])) / max(1, len(payload.get("sections", [])))
                if adapt_avg >= orig_avg and len(payload.get("sections", [])) <= len(content_data.get("sections", [])):
                    error_reasons.append("slower_pace requested but granularity did not increase and section length did not decrease")

            if "more_review" in direction_choices:
                orig_rev = len(content_data.get("review_questions", []))
                adapt_rev = len(payload.get("review_questions", []))
                if adapt_rev <= orig_rev:
                    error_reasons.append("more_review requested but review_questions did not increase")

            if "simplify_jargon" in direction_choices:
                orig_str = str(content_data).lower()
                adapt_str = str(payload).lower()
                jargon_markers = ["복잡한", "용어", "개념", "이론"]
                orig_jargon = sum(orig_str.count(j) for j in jargon_markers)
                adapt_jargon = sum(adapt_str.count(j) for j in jargon_markers)
                if adapt_jargon >= orig_jargon and "정의" not in adapt_str:
                    error_reasons.append("simplify_jargon requested but jargon markers did not decrease and definitions not found")

            if error_reasons:
                issues.append("adaptation_not_changed")
            return issues

        adapted_content_result = self._execute_provider_task(
            task_name="adapted_lesson_content", 
            lesson_id=lesson_id, 
            system_prompt=content_system_prompt, 
            user_payload=content_user_payload, 
            response_schema=LessonContent, 
            request_id_prefix=f"adapt_content_{lesson_id}",
            prompt_version="ll-adapt-content-v2",
            validator=content_validator
        )
        final_content = adapted_content_result.payload
        final_content_data = json.dumps(final_content, ensure_ascii=False)

        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            fb_row = cursor.execute("SELECT applied_status FROM feedback WHERE id = ?", (feedback.id,)).fetchone()
            if not fb_row or fb_row[0] != "not_applied":
                raise FeedbackAlreadyAppliedError(feedback.id)

            adaptation_summary = f"Adapted based on: {', '.join(feedback.direction_choices)}"
            if comprehension["free_text"]:
                adaptation_summary += f"; comprehension: {comprehension['free_text']}"
                
            create_lesson(
                self.conn, 
                learner_id=learner_id, 
                concept_id=original_lesson.concept_id, 
                lesson_number=original_lesson.lesson_number + 1, 
                prior_lesson_id=original_lesson.id, 
                generation_status="pending_review", 
                lesson_plan_json=adapted_data, 
                lesson_content_json=final_content_data, 
                adaptation_summary=adaptation_summary,
                commit=False,
                id=lesson_id
            )

            cursor.execute(
                "UPDATE feedback SET applied_status = ?, applied_to_lesson_id = ? WHERE id = ? AND lesson_id = ? AND learner_id = ? AND applied_status = 'not_applied'",
                ("applied_to_second", lesson_id, feedback.id, original_lesson.id, learner_id)
            )
            if cursor.rowcount != 1:
                raise GenerationError("Failed to atomically claim feedback")

            if final_content.get("code_examples"):
                for i, ex in enumerate(final_content["code_examples"]):
                    create_exercise(self.conn, lesson_id=lesson_id, question=f"다음 코드의 출력은 무엇인가요?\n```{ex.get('language', 'python')}\n{ex.get('code', '')}```", options=[], correct_answer=ex.get("expected_output", ""), explanation=ex.get("explanation", ""), difficulty="easy", sequence_order=i, commit=False)
            if final_content.get("review_questions"):
                base_seq = len(final_content.get("code_examples", []))
                for i, q in enumerate(final_content["review_questions"]):
                    create_exercise(self.conn, lesson_id=lesson_id, question=q.get("question", "") if isinstance(q, dict) else q, options=[], correct_answer=q.get("correct_answer", "") if isinstance(q, dict) else "", explanation=q.get("explanation", "") if isinstance(q, dict) else "", difficulty="medium", sequence_order=base_seq + i, commit=False)

            if idempotency_key:
                complete_idempotency_request(self.conn, op_key, result=json.dumps({"lesson_id": lesson_id, "status": "complete"}), commit=False)

            self.conn.commit()
            return lesson_id
        except Exception:
            self.conn.rollback()
            if idempotency_key:
                try:
                    from app.repositories.idempotency_repository import fail_idempotency_request
                    fail_idempotency_request(self.conn, op_key, commit=True)
                except Exception:
                    pass
            raise



    def finalize_and_close(self, lesson_id: str, learner_id: str) -> dict:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)
        self._validate_learner_active(learner_id)
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            close_lesson(self.conn, lesson_id, commit=False)
            prompt_tokens, completion_tokens = sum_tokens_by_lesson(self.conn, lesson_id)
            create_pilot_evidence(self.conn, learner_id=learner_id, lesson_id=lesson_id, evidence_type="pilot_complete", offer_description=f"Completed lesson {lesson_id}", commit=False)
            self.conn.commit()
            return {"lesson_id": lesson_id, "status": "closed", "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}
        except Exception:
            self.conn.rollback()
            raise

    def answer_exercise(self, exercise_id: str, learner_id: str, answer: str, idempotency_key: str = "") -> dict:
        self._validate_learner_active(learner_id)
        exercise = get_exercise_by_id(self.conn, exercise_id)
        if not exercise:
            raise GenerationError("Exercise not found")
        
        lesson = get_lesson_by_id(self.conn, exercise.lesson_id)
        if not lesson or lesson.learner_id != learner_id:
            raise ForeignFeedbackError(exercise_id, learner_id)
            
        op_key = f"exercise_answer:{exercise_id}:{learner_id}:{idempotency_key}" if idempotency_key else ""
        if op_key:
            existing = claim_idempotency_request(self.conn, op_key)
            if existing is None:
                raise GenerationError("Concurrent request in progress")
            if existing.status == "completed":
                try:
                    res = json.loads(existing.result)
                    return {"response_id": res.get("response_id"), "is_correct": res.get("is_correct"), "is_duplicate": True}
                except Exception:
                    return {"response_id": existing.resource_id, "is_correct": False, "is_duplicate": True}
            
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            existing_resp = cursor.execute("SELECT id, selected_answer, is_correct FROM exercise_responses WHERE exercise_id = ? AND learner_id = ?", (exercise_id, learner_id)).fetchone()
            if existing_resp:
                if existing_resp["selected_answer"] == answer:
                    self.conn.rollback()
                    return {"response_id": existing_resp["id"], "is_correct": bool(existing_resp["is_correct"]), "is_duplicate": True}
                else:
                    self.conn.rollback()
                    from app.pipeline.errors import ConflictingAnswerError
                    raise ConflictingAnswerError(exercise_id)

            is_correct = (answer.strip() == exercise.correct_answer.strip())
            
            resp = record_exercise_response(
                self.conn, 
                exercise_id=exercise_id, 
                learner_id=learner_id, 
                selected_answer=answer, 
                is_correct=is_correct, 
                commit=False
            )
            
            # update mastery
            correct_increment = 1 if is_correct else 0
            upsert_mastery(self.conn, learner_id=learner_id, concept_id=lesson.concept_id, practice_increment=1, correct_increment=correct_increment, commit=False)
            
            if op_key:
                complete_idempotency_request(self.conn, op_key, result=json.dumps({"response_id": resp.id, "is_correct": is_correct}), commit=False)
                
            self.conn.commit()
            return {"response_id": resp.id, "is_correct": is_correct, "is_duplicate": False}
        except Exception:
            self.conn.rollback()
            raise

    def get_learner_progress(self, learner_id: str) -> dict:
        self._validate_learner_active(learner_id)
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")
        lessons = get_lessons_by_learner(self.conn, learner_id)
        all_feedback = []
        for lesson in lessons:
            fb = self.conn.execute("SELECT * FROM feedback WHERE lesson_id = ?", (lesson.id,)).fetchall()
            all_feedback.extend(fb)
        return {"learner_id": learner_id, "topic": learner.topic, "total_lessons": len(lessons), "total_feedback": len(all_feedback), "pending_review_lessons": sum(1 for l in lessons if l.generation_status == "pending_review")}
