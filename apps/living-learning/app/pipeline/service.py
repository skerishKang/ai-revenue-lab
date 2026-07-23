"""Living Learning lesson pipeline.

This module orchestrates adaptive lesson generation with the Issue #37
contracts repaired:

* **Atomic idempotency (A)** — operations are guarded by an
  ``OperationIdentity`` claim with a DB-level UNIQUE key and CAS lifecycle.
* **Failed-claim recovery (B)** — a claim never sticks in ``pending``: on
  failure it is transitioned to ``failed_retryable`` (reclaimable), and a
  bounded lease allows stale claims to be reclaimed.
* **Feedback idempotency (C)** — the first request stores feedback; a duplicate
  returns the existing result with no re-application.
* **Operation identity (D)** — operation keys come from a typed value object,
  not ad-hoc string concatenation (removes the ``op_key`` scope bug).
* **Single transaction (E)** — the second-lesson persist (lesson, exercises,
  feedback application, mastery, adaptation decisions, generation-run finalize,
  claim completion) is one atomic transaction owned by the service layer.
* **AST allowlist (F)** and **answer grounding (G)** — delegated to
  ``app.pipeline.code_safety`` and ``app.pipeline.validation``.
* **Provider accounting (I)** — every provider call (incl. failures and repair
  calls) is recorded per attempt group and aggregated; tokens are nullable.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any

from app.domain.models import LessonContent, LessonPlan, ProviderResult
from app.domain.operation import (
    OperationIdentity,
    TASK_EXERCISE_ANSWER,
    TASK_FEEDBACK,
    TASK_FIRST_LESSON,
    TASK_SECOND_LESSON,
)
from app.repositories import (
    ClaimHandle,
    claim_operation,
    complete_operation,
    fail_operation,
    close_lesson,
    create_curriculum,
    create_exercise,
    create_feedback,
    create_generation_run,
    create_learner,
    create_lesson,
    create_pilot_evidence,
    finalize_attempt_group,
    get_concept_by_id,
    get_exercise_by_id,
    get_feedback_by_id,
    get_learner_by_id,
    get_lesson_by_id,
    get_lessons_by_learner,
    is_feedback_applied,
    record_adaptation_decision,
    record_comprehension_response,
    record_exercise_response,
    sum_tokens_by_lesson,
    upsert_mastery,
    validate_prerequisites,
)
from app.pipeline.errors import (
    AdaptationNotChangedError,
    ComprehensionRequiredError,
    ConcurrentOperationError,
    ContentValidationError,
    FeedbackAlreadyAppliedError,
    ForeignFeedbackError,
    GenerationError,
    LearnerInactiveError,
    LostClaimOwnershipError,
    NonRetryableError,
    OperationTerminalError,
    PrerequisiteNotMetError,
    RetryExhaustedError,
    UnsafeContentError,
)
from app.pipeline.prompts import (
    ADAPTED_LESSON_CONTENT_PROMPT,
    ADAPTED_LESSON_PROMPT,
    LESSON_CONTENT_PROMPT,
    LESSON_PLAN_PROMPT,
)
from app.pipeline.validation import validate_lesson_content, validate_safe_content
from app.repositories.history_repository import get_latest_diagnostic_snapshot
from app.ai.base import AIProvider

MAX_RETRIES = 3

RETRYABLE_ERROR_CATEGORIES = frozenset(
    {"timeout", "rate_limit", "connection_error", "transient_provider_error"}
)

NON_RETRYABLE_ERROR_CATEGORIES = frozenset(
    {
        "authentication_error",
        "authorization_error",
        "provider_refusal",
        "unsafe_content",
        "invalid_request",
        "schema_mismatch",
    }
)


def _classify_exception(exc: Exception) -> tuple[str, bool]:
    """Map an exception to (error_category, is_retryable).

    Timeout and connection failures get distinct categories (not collapsed into
    a single transient bucket) per the provider-accounting contract.
    """
    category = getattr(exc, "error_category", None)
    if category:
        if category in RETRYABLE_ERROR_CATEGORIES:
            return category, True
        if category in NON_RETRYABLE_ERROR_CATEGORIES:
            return category, False
        return category, False
    if isinstance(exc, TimeoutError):
        return "timeout", True
    if isinstance(exc, ConnectionError):
        return "connection_error", True
    return "unknown_exception", False


class LessonPipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: AIProvider,
        settings: Any = None,
    ) -> None:
        self.conn = conn
        self.provider = provider
        self.settings = settings or type(
            "Settings",
            (),
            {
                "provider_type": "mock",
                "provider_model": "mock-fixture",
                "database_url": ":memory:",
            },
        )()

    # ------------------------------------------------------------------
    # Transaction + claim helpers
    # ------------------------------------------------------------------
    def _begin_immediate(self) -> None:
        if self.conn.in_transaction:
            # A stray implicit transaction would make BEGIN IMMEDIATE fail; our
            # flow commits accounting rows before opening the persist txn, so
            # this is defensive only.
            self.conn.commit()
        self.conn.execute("BEGIN IMMEDIATE")

    def _acquire_claim(self, identity: OperationIdentity):
        """Atomically acquire the operation claim as a durable lock.

        Commits the claim so concurrent callers see it during generation.
        Returns the ``ClaimOutcome``; the caller must handle ``replay`` (return
        the cached result). Raises on conflict (another active owner) or
        terminal failure. Doing the replay detection here — rather than in a
        separate pre-check — closes the race where a concurrent request
        completes between the pre-check and the claim.
        """
        from app.repositories import ClaimOutcome  # noqa: F401

        self._begin_immediate()
        try:
            outcome = claim_operation(self.conn, identity)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        if outcome.conflict or outcome.record is None:
            raise ConcurrentOperationError(identity.operation_key)
        if outcome.terminal:
            raise OperationTerminalError(identity.operation_key)
        return outcome

    @staticmethod
    def _replay_result(outcome) -> dict | None:
        """Return the cached result dict if the claim was a completed replay."""
        if outcome.replay and outcome.record is not None and outcome.record.result_json:
            try:
                return json.loads(outcome.record.result_json)
            except (ValueError, TypeError):
                return {}
        return None

    def _mark_claim_retryable(self, handle: ClaimHandle | None) -> None:
        """Recover a claim to failed_retryable so a retry can reclaim it.

        If we are no longer the owner (a stale owner whose claim was reclaimed),
        ``fail_operation`` raises ``LostClaimOwnershipError``; we swallow it
        because the new owner now manages the claim lifecycle.
        """
        if handle is None:
            return
        try:
            self._begin_immediate()
            fail_operation(self.conn, handle, terminal=False)
            self.conn.commit()
        except LostClaimOwnershipError:
            try:
                self.conn.rollback()
            except Exception:
                pass
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Learner validation
    # ------------------------------------------------------------------
    def _validate_learner_active(self, learner_id: str) -> None:
        learner = get_learner_by_id(self.conn, learner_id)
        if not learner:
            raise GenerationError("Learner not found")
        if learner.status not in ("active",):
            raise LearnerInactiveError(learner_id, learner.status)

    def _latest_snapshot_id(self, learner_id: str) -> str | None:
        """Diagnostic snapshot that drives generation (adaptation provenance)."""
        snapshot = get_latest_diagnostic_snapshot(self.conn, learner_id)
        return snapshot.id if snapshot else None

    # ------------------------------------------------------------------
    # Provider task execution with accounting
    # ------------------------------------------------------------------
    def _execute_provider_task(
        self,
        task_name: str,
        attempt_group_id: str,
        lesson_id: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type,
        prompt_version: str = "",
        validator=None,
    ) -> ProviderResult:
        last_category = "unknown_exception"
        for attempt in range(MAX_RETRIES):
            req_id = f"{attempt_group_id}_{attempt}"
            started = time.perf_counter()
            started_at = _iso_now()
            try:
                res = self.provider.generate_structured(
                    task_name=task_name,
                    system_prompt=system_prompt,
                    user_payload=user_payload,
                    response_schema=response_schema,
                    request_id=req_id,
                )
                latency_ms = (time.perf_counter() - started) * 1000.0

                if res.success and validator:
                    issues = validator(res.payload)
                    if issues:
                        res.success = False
                        res.error_category = issues[0]
                        res.error_message = f"validation_failed:{issues[0]}"

                validation_result = "passed" if res.success else "failed"
                create_generation_run(
                    self.conn,
                    task_type=task_name,
                    attempt_group_id=attempt_group_id,
                    attempt_number=attempt + 1,
                    request_id=req_id,
                    provider=getattr(res, "provider", "mock"),
                    advertised_model=getattr(res, "model", ""),
                    cost_class=getattr(res, "cost_class", "free"),
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                    prompt_tokens=_tokens_or_none(getattr(res, "prompt_tokens", 0)),
                    completion_tokens=_tokens_or_none(getattr(res, "completion_tokens", 0)),
                    error_category=res.error_category if not res.success else "",
                    error_message=_sanitize_error(res.error_message if not res.success else ""),
                    lesson_id=lesson_id,
                    success=res.success,
                    validation_result=validation_result,
                    started_at=started_at,
                    completed_at=_iso_now(),
                    commit=True,
                )

                if res.success:
                    return res

                last_category = res.error_category or "unknown_exception"
                if last_category in RETRYABLE_ERROR_CATEGORIES:
                    if attempt >= MAX_RETRIES - 1:
                        raise RetryExhaustedError(task_name, attempt + 1)
                    continue
                # Non-retryable provider-reported failure.
                if last_category.startswith(
                    ("unsafe_", "markup_", "credential_", "fabricated_")
                ):
                    raise UnsafeContentError([last_category])
                raise NonRetryableError(f"{task_name} failed: {last_category}")

            except (RetryExhaustedError, UnsafeContentError, NonRetryableError):
                raise
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000.0
                error_category, is_retryable = _classify_exception(exc)
                last_category = error_category
                # Preserve provider usage if the exception carries a result.
                prompt_tokens = None
                completion_tokens = None
                provider = getattr(self.provider, "provider_type", "mock")
                model = getattr(self.provider, "model", "")
                carried = getattr(exc, "res", None)
                if carried is not None:
                    prompt_tokens = _tokens_or_none(getattr(carried, "prompt_tokens", 0))
                    completion_tokens = _tokens_or_none(getattr(carried, "completion_tokens", 0))
                    provider = getattr(carried, "provider", provider)
                    model = getattr(carried, "model", model)

                create_generation_run(
                    self.conn,
                    task_type=task_name,
                    attempt_group_id=attempt_group_id,
                    attempt_number=attempt + 1,
                    request_id=req_id,
                    provider=provider,
                    advertised_model=model,
                    prompt_version=prompt_version,
                    latency_ms=latency_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    error_category=error_category,
                    error_message=_sanitize_error(error_category),
                    lesson_id=lesson_id,
                    success=False,
                    validation_result="error",
                    started_at=started_at,
                    completed_at=_iso_now(),
                    commit=True,
                )

                if is_retryable and attempt < MAX_RETRIES - 1:
                    continue
                if is_retryable:
                    raise RetryExhaustedError(task_name, attempt + 1) from exc
                if error_category.startswith(
                    ("unsafe_", "markup_", "credential_", "fabricated_")
                ):
                    raise UnsafeContentError([error_category]) from exc
                raise NonRetryableError(error_category) from exc

        raise RetryExhaustedError(task_name, MAX_RETRIES)

    # ------------------------------------------------------------------
    # Adaptation materiality (extracted for testability — blocker J)
    # ------------------------------------------------------------------
    def _verify_adaptation_changes(
        self,
        orig_plan: dict,
        orig_content: dict,
        adapt_plan: dict,
        adapt_content: dict,
        direction_choices: set[str] | list[str],
    ) -> None:
        """Raise AdaptationNotChangedError if the adaptation is not material.

        Checks both that *something* changed (not metadata-only) and that each
        requested feedback direction produced its intended structural change.
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

        if extract_core(orig_plan, orig_content) == extract_core(adapt_plan, adapt_content):
            error_reasons.append("metadata-only changes")

        orig_sections = orig_content.get("sections", []) or []
        adapt_sections = adapt_content.get("sections", []) or []

        if "reduce_theory" in directions:
            orig_theory = sum(len(str(s)) for s in orig_sections)
            adapt_theory = sum(len(str(s)) for s in adapt_sections)
            orig_prac = len(orig_content.get("code_examples", [])) + len(orig_content.get("review_questions", []))
            adapt_prac = len(adapt_content.get("code_examples", [])) + len(adapt_content.get("review_questions", []))
            if not (adapt_theory < orig_theory or adapt_prac > orig_prac):
                error_reasons.append("reduce_theory: theory did not decrease and practice did not increase")

        if "more_examples" in directions:
            if len(adapt_content.get("code_examples", [])) <= len(orig_content.get("code_examples", [])):
                error_reasons.append("more_examples: code_examples did not increase")

        if "code_first" in directions:
            first_sect = adapt_sections[0] if adapt_sections else {}
            has_code = first_sect.get("includes_code") and first_sect.get("code_snippet")
            if not has_code:
                code_examples = adapt_content.get("code_examples") or []
                first_ex = code_examples[0] if code_examples else {}
                if not first_ex.get("code"):
                    error_reasons.append("code_first: first section has no code and first example is not code")

        if "slower_pace" in directions:
            orig_avg = sum(len(str(s)) for s in orig_sections) / max(1, len(orig_sections))
            adapt_avg = sum(len(str(s)) for s in adapt_sections) / max(1, len(adapt_sections))
            if adapt_avg >= orig_avg and len(adapt_sections) <= len(orig_sections):
                error_reasons.append("slower_pace: granularity did not increase and length did not decrease")

        if "more_review" in directions:
            if len(adapt_content.get("review_questions", [])) <= len(orig_content.get("review_questions", [])):
                error_reasons.append("more_review: review_questions did not increase")

        if "simplify_jargon" in directions:
            orig_str = str(orig_content).lower()
            adapt_str = str(adapt_content).lower()
            markers = ["복잡한", "용어", "개념", "이론"]
            orig_jargon = sum(orig_str.count(m) for m in markers)
            adapt_jargon = sum(adapt_str.count(m) for m in markers)
            if adapt_jargon >= orig_jargon and "정의" not in adapt_str:
                error_reasons.append("simplify_jargon: jargon did not decrease and no definitions added")

        if error_reasons:
            raise AdaptationNotChangedError({"reasons": error_reasons})

    def _build_adaptation_decisions(
        self,
        orig_content: dict,
        adapt_content: dict,
        directions: set[str],
    ) -> list[dict]:
        """Derive concrete per-dimension change records for the adaptation."""
        decisions: list[dict] = []
        orig_ex = len(orig_content.get("code_examples", []))
        adapt_ex = len(adapt_content.get("code_examples", []))
        if orig_ex != adapt_ex:
            decisions.append(
                {
                    "dimension": "example_count",
                    "before_value": str(orig_ex),
                    "after_value": str(adapt_ex),
                    "reason": "more_examples feedback increased code examples",
                }
            )
        orig_rev = len(orig_content.get("review_questions", []))
        adapt_rev = len(adapt_content.get("review_questions", []))
        if orig_rev != adapt_rev:
            decisions.append(
                {
                    "dimension": "review_question_count",
                    "before_value": str(orig_rev),
                    "after_value": str(adapt_rev),
                    "reason": "more_review feedback increased review questions",
                }
            )
        if "code_first" in directions:
            decisions.append(
                {
                    "dimension": "explanation_order",
                    "before_value": "explanation_first",
                    "after_value": "code_first",
                    "reason": "code_first feedback moved code before explanation",
                }
            )
        if "slower_pace" in directions:
            decisions.append(
                {
                    "dimension": "pacing",
                    "before_value": "standard",
                    "after_value": "slower",
                    "reason": "slower_pace feedback split content into finer steps",
                }
            )
        if "simplify_jargon" in directions:
            decisions.append(
                {
                    "dimension": "terminology",
                    "before_value": "standard",
                    "after_value": "inline_definitions",
                    "reason": "simplify_jargon feedback added inline term definitions",
                }
            )
        if "reduce_theory" in directions:
            decisions.append(
                {
                    "dimension": "theory_density",
                    "before_value": "standard",
                    "after_value": "reduced",
                    "reason": "reduce_theory feedback shortened explanation sections",
                }
            )
        return decisions

    # ------------------------------------------------------------------
    # Learner + curriculum bootstrap
    # ------------------------------------------------------------------
    def create_learner_and_session(self, topic: str, **preferences) -> dict:
        cursor = self.conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            learner = create_learner(self.conn, topic=topic, **preferences, commit=False)
            curriculum = create_curriculum(self.conn, topic=topic, commit=False)
            session_id = f"sess_{secrets.token_urlsafe(16)}"
            cursor.execute(
                "INSERT INTO learner_sessions (session_id, learner_id, curriculum_id, "
                "current_lesson_sequence, last_activity_at, created_at) "
                "VALUES (?, ?, ?, 0, datetime('now'), datetime('now'))",
                (session_id, learner.id, curriculum.id),
            )
            concept_map = [
                ("variables", "변수", [], 0),
                ("values", "값", [], 1),
                ("conditionals", "간단한 조건문", ["variables", "values"], 2),
                ("python_example", "Python 예제", ["variables", "values", "conditionals"], 3),
            ]
            concept_ids: dict[str, str] = {}
            for eng_name, korean_name, prereqs, seq_order in concept_map:
                prereq_ids = [concept_ids[p] for p in prereqs if p in concept_ids]
                concept = self._create_concept_with_stable_id(
                    cursor, curriculum.id, eng_name, korean_name, prereq_ids, seq_order
                )
                concept_ids[eng_name] = concept.id
                upsert_mastery(self.conn, learner_id=learner.id, concept_id=concept.id, commit=False)
            self.conn.commit()
            return {
                "learner_id": learner.id,
                "session_id": session_id,
                "curriculum_id": curriculum.id,
            }
        except Exception:
            self.conn.rollback()
            raise

    def _create_concept_with_stable_id(
        self,
        cursor: sqlite3.Cursor,
        curriculum_id: str,
        name: str,
        description: str,
        prerequisites: list[str],
        sequence_order: int,
    ) -> Any:
        import hashlib

        name_slug = name.strip().lower()
        key = f"{curriculum_id}:{name_slug}".encode("utf-8")
        concept_id = f"concept_{hashlib.md5(key).hexdigest()}"

        existing = cursor.execute("SELECT * FROM concepts WHERE id = ?", (concept_id,)).fetchone()
        if existing:
            cursor.execute(
                "UPDATE concepts SET prerequisites = ?, sequence_order = ? WHERE id = ?",
                (json.dumps(prerequisites), sequence_order, concept_id),
            )
        else:
            cursor.execute(
                "INSERT INTO concepts (id, curriculum_id, name, description, prerequisites, "
                "sequence_order, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (concept_id, curriculum_id, name, description, json.dumps(prerequisites), sequence_order),
            )
        return type(
            "ConceptRecord",
            (),
            {
                "id": concept_id,
                "curriculum_id": curriculum_id,
                "name": name,
                "description": description,
                "prerequisites": prerequisites,
                "sequence_order": sequence_order,
            },
        )()

    # ------------------------------------------------------------------
    # First lesson
    # ------------------------------------------------------------------
    def start_first_lesson(self, learner_id: str, concept_id: str, idempotency_key: str = "") -> str:
        self._validate_learner_active(learner_id)

        handle: ClaimHandle | None = None
        if idempotency_key:
            identity = OperationIdentity(
                task_type=TASK_FIRST_LESSON,
                learner_id=learner_id,
                client_idempotency_key=idempotency_key,
                prior_lesson_id=concept_id,
            )
            outcome = self._acquire_claim(identity)
            replay = self._replay_result(outcome)
            if replay is not None:
                return replay.get("lesson_id", "")
            handle = outcome.handle

        try:
            valid, missing = validate_prerequisites(self.conn, concept_id, learner_id)
            if not valid:
                raise PrerequisiteNotMetError(concept_id, missing)

            learner = get_learner_by_id(self.conn, learner_id)
            concept = get_concept_by_id(self.conn, concept_id)
            if not learner or not concept:
                raise GenerationError("Learner or concept not found")

            session = self.conn.execute(
                "SELECT curriculum_id FROM learner_sessions WHERE learner_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (learner_id,),
            ).fetchone()
            if not session or session[0] != concept.curriculum_id:
                raise GenerationError(
                    f"Concept {concept_id} does not belong to the learner's session curriculum."
                )

            candidate_id = f"lesson_{secrets.token_urlsafe(16)}"
            return self._generate_full_lesson_content(candidate_id, learner, concept, handle)
        except LostClaimOwnershipError:
            # Stale owner: product writes (if any) were rolled back; do not touch the claim.
            raise
        except Exception:
            self._mark_claim_retryable(handle)
            raise

    def _generate_full_lesson_content(
        self, lesson_id: str, learner, concept, handle: ClaimHandle | None
    ) -> str:
        attempt_group = f"{lesson_id}:first"
        plan_user_payload = {
            "topic": learner.topic,
            "concept_name": concept.name,
            "example_preference": getattr(learner, "example_preference", "balanced"),
            "theory_density": getattr(learner, "theory_density", "standard"),
            "jargon_level": getattr(learner, "jargon_level", "standard"),
            "review_question_count": getattr(learner, "review_question_count", 2),
        }
        plan_system_prompt = LESSON_PLAN_PROMPT.format(**plan_user_payload)

        def plan_validator(payload):
            return validate_safe_content(json.dumps(payload, ensure_ascii=False))

        plan_result = self._execute_provider_task(
            task_name="lesson_plan",
            attempt_group_id=attempt_group,
            lesson_id=lesson_id,
            system_prompt=plan_system_prompt,
            user_payload=plan_user_payload,
            response_schema=LessonPlan,
            prompt_version="ll-plan-v1",
            validator=plan_validator,
        )
        plan_payload = plan_result.payload
        plan_data = json.dumps(plan_payload, ensure_ascii=False)

        content_user_payload = {
            "example_preference": plan_user_payload["example_preference"],
            "theory_density": plan_user_payload["theory_density"],
            "jargon_level": plan_user_payload["jargon_level"],
            "pacing_feedback_style": "standard",
            "lesson_plan": plan_data,
        }
        content_system_prompt = LESSON_CONTENT_PROMPT.format(**content_user_payload)

        def content_validator(payload):
            issues = validate_lesson_content(payload, plan_payload)
            if issues:
                raise ContentValidationError(issues)
            return []

        content_result = self._execute_provider_task(
            task_name="lesson_content",
            attempt_group_id=attempt_group,
            lesson_id=lesson_id,
            system_prompt=content_system_prompt,
            user_payload=content_user_payload,
            response_schema=LessonContent,
            prompt_version="ll-content-v1",
            validator=content_validator,
        )
        content_payload = content_result.payload
        content_data = json.dumps(content_payload, ensure_ascii=False)

        # Single atomic persist transaction.
        self._begin_immediate()
        try:
            create_lesson(
                self.conn,
                learner_id=learner.id,
                concept_id=concept.id,
                lesson_number=1,
                generation_status="pending_review",
                lesson_plan_json=plan_data,
                lesson_content_json=content_data,
                source_diagnostic_snapshot_id=self._latest_snapshot_id(learner.id),
                commit=False,
                id=lesson_id,
            )
            self._persist_exercises(lesson_id, content_payload)
            finalize_attempt_group(self.conn, attempt_group, validation_result="passed", commit=False)
            if handle is not None:
                # Fenced CAS: if we are no longer the owner (stale), this raises
                # LostClaimOwnershipError and the whole product transaction below
                # rolls back — a stale owner's lesson never becomes product state.
                complete_operation(
                    self.conn,
                    handle,
                    result_json=json.dumps({"lesson_id": lesson_id, "status": "complete"}),
                )
            self.conn.commit()
            return lesson_id
        except LostClaimOwnershipError:
            self.conn.rollback()
            raise
        except Exception:
            self.conn.rollback()
            self._mark_claim_retryable(handle)
            raise

    def _persist_exercises(self, lesson_id: str, content_payload: dict) -> None:
        if content_payload.get("code_examples"):
            for i, ex in enumerate(content_payload["code_examples"]):
                create_exercise(
                    self.conn,
                    lesson_id=lesson_id,
                    question=f"다음 코드의 출력은 무엇인가요?\n```{ex.get('language', 'python')}\n{ex.get('code', '')}```",
                    options=[],
                    correct_answer=ex.get("expected_output", ""),
                    explanation=ex.get("explanation", ""),
                    difficulty="easy",
                    sequence_order=i,
                    commit=False,
                )
        if content_payload.get("review_questions"):
            base_seq = len(content_payload.get("code_examples", []))
            for i, q in enumerate(content_payload["review_questions"]):
                create_exercise(
                    self.conn,
                    lesson_id=lesson_id,
                    question=q.get("question", "") if isinstance(q, dict) else q,
                    options=[],
                    correct_answer=q.get("correct_answer", "") if isinstance(q, dict) else "",
                    explanation=q.get("explanation", "") if isinstance(q, dict) else "",
                    difficulty="medium",
                    sequence_order=base_seq + i,
                    commit=False,
                )

    # ------------------------------------------------------------------
    # Comprehension
    # ------------------------------------------------------------------
    def record_comprehension(
        self,
        lesson_id: str,
        learner_id: str,
        understood: bool,
        difficulty_rating: int = 3,
        free_text: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)
        self._begin_immediate()
        try:
            resp = record_comprehension_response(
                self.conn,
                lesson_id=lesson_id,
                learner_id=learner_id,
                understood=understood,
                difficulty_rating=difficulty_rating,
                free_text=free_text,
                commit=False,
            )
            self.conn.execute(
                "UPDATE lessons SET updated_at = datetime('now') WHERE id = ?", (lesson_id,)
            )
            self.conn.commit()
            return {"response_id": resp.id, "success": True}
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Feedback (blocker C: first stores, duplicate replays)
    # ------------------------------------------------------------------
    def record_feedback(
        self,
        lesson_id: str,
        learner_id: str,
        direction_choices: list[str],
        free_text: str = "",
        idempotency_key: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)

        valid_directions = {
            "reduce_theory",
            "more_examples",
            "code_first",
            "slower_pace",
            "more_review",
            "simplify_jargon",
        }
        for d in direction_choices:
            if d not in valid_directions:
                raise GenerationError(f"Unknown feedback direction: {d}")

        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)

        handle: ClaimHandle | None = None
        if idempotency_key:
            identity = OperationIdentity(
                task_type=TASK_FEEDBACK,
                learner_id=learner_id,
                client_idempotency_key=idempotency_key,
                prior_lesson_id=lesson_id,
            )
            outcome = self._acquire_claim(identity)
            replay = self._replay_result(outcome)
            if replay is not None:
                return {"feedback_id": replay.get("feedback_id", ""), "is_duplicate": True}
            handle = outcome.handle

        try:
            self._begin_immediate()
            try:
                feedback = create_feedback(
                    self.conn,
                    lesson_id=lesson_id,
                    learner_id=learner_id,
                    lesson_generation=lesson.lesson_number,
                    direction_choices=direction_choices,
                    free_text=free_text,
                    commit=False,
                )
                if handle is not None:
                    complete_operation(
                        self.conn,
                        handle,
                        result_json=json.dumps({"feedback_id": feedback.id}),
                    )
                self.conn.commit()
                return {"feedback_id": feedback.id, "is_duplicate": False}
            except LostClaimOwnershipError:
                self.conn.rollback()
                raise
            except Exception:
                self.conn.rollback()
                raise
        except LostClaimOwnershipError:
            raise
        except Exception:
            self._mark_claim_retryable(handle)
            raise

    # ------------------------------------------------------------------
    # Second lesson (blockers D + E)
    # ------------------------------------------------------------------
    def process_feedback_and_generate_second_lesson(
        self,
        lesson_id: str,
        learner_id: str,
        comprehension_response_id: str,
        feedback_id: str,
        idempotency_key: str = "",
    ) -> dict:
        self._validate_learner_active(learner_id)

        handle: ClaimHandle | None = None
        if idempotency_key:
            identity = OperationIdentity(
                task_type=TASK_SECOND_LESSON,
                learner_id=learner_id,
                client_idempotency_key=idempotency_key,
                prior_lesson_id=lesson_id,
                comprehension_response_id=comprehension_response_id,
                feedback_id=feedback_id,
            )
            outcome = self._acquire_claim(identity)
            replay = self._replay_result(outcome)
            if replay is not None:
                return {"lesson_id": replay.get("lesson_id", ""), "adaptation_verified": True}
            handle = outcome.handle

        try:
            original_lesson = get_lesson_by_id(self.conn, lesson_id)
            if not original_lesson:
                raise GenerationError("Lesson not found")
            if original_lesson.generation_status not in (
                "pending_review",
                "published",
                "closed",
                "input_received",
            ):
                raise GenerationError(
                    f"Prior lesson is not in an accepted completed state: {original_lesson.generation_status}"
                )
            if (
                not original_lesson.lesson_plan_json
                or not original_lesson.lesson_content_json
                or original_lesson.lesson_plan_json == "{}"
                or original_lesson.lesson_content_json == "{}"
            ):
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
            new_lesson_id = self._generate_adapted_content(
                lesson_id=candidate_id,
                learner_id=learner_id,
                original_lesson=original_lesson,
                feedback=feedback,
                comprehension=comprehension,
                handle=handle,
            )
            return {"lesson_id": new_lesson_id, "adaptation_verified": True}
        except LostClaimOwnershipError:
            raise
        except Exception:
            self._mark_claim_retryable(handle)
            raise

    def _generate_adapted_content(
        self,
        lesson_id: str,
        learner_id: str,
        original_lesson,
        feedback,
        comprehension,
        handle: ClaimHandle | None,
    ) -> str:
        learner = get_learner_by_id(self.conn, learner_id)
        concept = get_concept_by_id(self.conn, original_lesson.concept_id)
        if not learner or not concept:
            raise GenerationError("Learner or concept not found")

        plan_data = json.loads(original_lesson.lesson_plan_json)
        content_data = json.loads(original_lesson.lesson_content_json)
        attempt_group = f"{lesson_id}:second"

        payload_kwargs = {
            "original_plan": json.dumps(plan_data, ensure_ascii=False),
            "original_content": json.dumps(content_data, ensure_ascii=False),
            "direction_choices": ", ".join(feedback.direction_choices),
            "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
            "comprehension_understood": str(bool(comprehension["understood"])),
            "comprehension_difficulty": str(comprehension["difficulty_rating"]),
            "comprehension_text": comprehension["free_text"] or "",
        }
        plan_system_prompt = ADAPTED_LESSON_PROMPT.format(**payload_kwargs)

        def plan_validator(payload):
            return validate_safe_content(json.dumps(payload, ensure_ascii=False))

        adapted_plan_result = self._execute_provider_task(
            task_name="adapted_lesson_plan",
            attempt_group_id=attempt_group,
            lesson_id=lesson_id,
            system_prompt=plan_system_prompt,
            user_payload=payload_kwargs,
            response_schema=LessonPlan,
            prompt_version="ll-adapt-plan-v1",
            validator=plan_validator,
        )
        adapted_payload = adapted_plan_result.payload
        adapted_data = json.dumps(adapted_payload, ensure_ascii=False)

        content_user_payload = {
            "example_preference": getattr(learner, "example_preference", "balanced"),
            "theory_density": getattr(learner, "theory_density", "standard"),
            "jargon_level": getattr(learner, "jargon_level", "standard"),
            "pacing_feedback_style": "adapted",
            "lesson_plan": adapted_data,
            "original_plan": json.dumps(plan_data, ensure_ascii=False),
            "original_content": json.dumps(content_data, ensure_ascii=False),
            "direction_choices": ", ".join(feedback.direction_choices),
            "free_text_section": f"Additional feedback: {feedback.free_text}" if feedback.free_text else "",
            "comprehension_understood": str(bool(comprehension["understood"])),
            "comprehension_difficulty": str(comprehension["difficulty_rating"]),
            "comprehension_text": comprehension["free_text"] or "",
        }
        content_system_prompt = ADAPTED_LESSON_CONTENT_PROMPT.format(**content_user_payload)

        directions = set(feedback.direction_choices)

        def content_validator(payload):
            issues = validate_lesson_content(payload, adapted_payload)
            if issues:
                raise ContentValidationError(issues)
            # Material adaptation check (blocker: must be materially different).
            self._verify_adaptation_changes(plan_data, content_data, adapted_payload, payload, directions)
            return []

        adapted_content_result = self._execute_provider_task(
            task_name="adapted_lesson_content",
            attempt_group_id=attempt_group,
            lesson_id=lesson_id,
            system_prompt=content_system_prompt,
            user_payload=content_user_payload,
            response_schema=LessonContent,
            prompt_version="ll-adapt-content-v2",
            validator=content_validator,
        )
        final_content = adapted_content_result.payload
        final_content_data = json.dumps(final_content, ensure_ascii=False)

        # Single atomic persist transaction (blocker E).
        self._begin_immediate()
        try:
            adaptation_summary = f"Adapted based on: {', '.join(feedback.direction_choices)}"
            if comprehension["free_text"]:
                adaptation_summary += f"; comprehension: {comprehension['free_text']}"

            # Create the lesson first so the feedback application (which records
            # applied_to_lesson_id with a FK to lessons) references an existing
            # row. If the feedback CAS below fails, the whole transaction —
            # including this lesson — rolls back.
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
                source_diagnostic_snapshot_id=self._latest_snapshot_id(learner_id),
                commit=False,
                id=lesson_id,
            )

            # CAS feedback application — exactly-once within the lock.
            cur = self.conn.execute(
                "UPDATE feedback SET applied_status = ?, applied_to_lesson_id = ? "
                "WHERE id = ? AND lesson_id = ? AND learner_id = ? AND applied_status = 'not_applied'",
                ("applied_to_second", lesson_id, feedback.id, original_lesson.id, learner_id),
            )
            if cur.rowcount != 1:
                raise FeedbackAlreadyAppliedError(feedback.id)

            self._persist_exercises(lesson_id, final_content)

            # Mastery update reflecting the adaptation cycle.
            upsert_mastery(
                self.conn,
                learner_id=learner_id,
                concept_id=original_lesson.concept_id,
                practice_increment=1,
                correct_increment=1 if comprehension["understood"] else 0,
                commit=False,
            )

            # Independent adaptation-decision records.
            for decision in self._build_adaptation_decisions(content_data, final_content, directions):
                record_adaptation_decision(
                    self.conn,
                    learner_id=learner_id,
                    prior_lesson_id=original_lesson.id,
                    next_lesson_id=lesson_id,
                    signal_type="feedback",
                    signal_reference_id=feedback.id,
                    dimension=decision["dimension"],
                    before_value=decision["before_value"],
                    after_value=decision["after_value"],
                    reason=decision["reason"],
                    commit=False,
                )

            finalize_attempt_group(self.conn, attempt_group, validation_result="passed", commit=False)

            if handle is not None:
                # Fenced CAS: a stale owner raises LostClaimOwnershipError and the
                # entire product transaction (lesson, feedback application, mastery,
                # adaptation decisions) rolls back.
                complete_operation(
                    self.conn,
                    handle,
                    result_json=json.dumps({"lesson_id": lesson_id, "status": "complete"}),
                )

            self.conn.commit()
            return lesson_id
        except LostClaimOwnershipError:
            self.conn.rollback()
            raise
        except Exception:
            self.conn.rollback()
            self._mark_claim_retryable(handle)
            raise

    # ------------------------------------------------------------------
    # Finalize / close
    # ------------------------------------------------------------------
    def finalize_and_close(self, lesson_id: str, learner_id: str) -> dict:
        lesson = get_lesson_by_id(self.conn, lesson_id)
        if not lesson:
            raise GenerationError("Lesson not found")
        if lesson.learner_id != learner_id:
            raise ForeignFeedbackError(lesson_id, learner_id)
        self._validate_learner_active(learner_id)
        self._begin_immediate()
        try:
            close_lesson(self.conn, lesson_id, commit=False)
            prompt_tokens, completion_tokens = sum_tokens_by_lesson(self.conn, lesson_id)
            create_pilot_evidence(
                self.conn,
                learner_id=learner_id,
                lesson_id=lesson_id,
                evidence_type="pilot_complete",
                offer_description=f"Completed lesson {lesson_id}",
                commit=False,
            )
            self.conn.commit()
            return {
                "lesson_id": lesson_id,
                "status": "closed",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Exercise answering
    # ------------------------------------------------------------------
    def answer_exercise(
        self, exercise_id: str, learner_id: str, answer: str, idempotency_key: str = ""
    ) -> dict:
        self._validate_learner_active(learner_id)
        exercise = get_exercise_by_id(self.conn, exercise_id)
        if not exercise:
            raise GenerationError("Exercise not found")

        lesson = get_lesson_by_id(self.conn, exercise.lesson_id)
        if not lesson or lesson.learner_id != learner_id:
            raise ForeignFeedbackError(exercise_id, learner_id)

        handle: ClaimHandle | None = None
        if idempotency_key:
            identity = OperationIdentity(
                task_type=TASK_EXERCISE_ANSWER,
                learner_id=learner_id,
                client_idempotency_key=idempotency_key,
                exercise_id=exercise_id,
            )
            outcome = self._acquire_claim(identity)
            replay = self._replay_result(outcome)
            if replay is not None:
                return {
                    "response_id": replay.get("response_id"),
                    "is_correct": replay.get("is_correct"),
                    "is_duplicate": True,
                }
            handle = outcome.handle

        try:
            self._begin_immediate()
            try:
                existing_resp = self.conn.execute(
                    "SELECT id, selected_answer, is_correct FROM exercise_responses "
                    "WHERE exercise_id = ? AND learner_id = ?",
                    (exercise_id, learner_id),
                ).fetchone()
                if existing_resp:
                    self.conn.rollback()
                    if existing_resp["selected_answer"] == answer:
                        return {
                            "response_id": existing_resp["id"],
                            "is_correct": bool(existing_resp["is_correct"]),
                            "is_duplicate": True,
                        }
                    from app.pipeline.errors import ConflictingAnswerError

                    raise ConflictingAnswerError(exercise_id)

                is_correct = answer.strip() == exercise.correct_answer.strip()
                resp = record_exercise_response(
                    self.conn,
                    exercise_id=exercise_id,
                    learner_id=learner_id,
                    selected_answer=answer,
                    is_correct=is_correct,
                    commit=False,
                )
                upsert_mastery(
                    self.conn,
                    learner_id=learner_id,
                    concept_id=lesson.concept_id,
                    practice_increment=1,
                    correct_increment=1 if is_correct else 0,
                    commit=False,
                )
                if handle is not None:
                    complete_operation(
                        self.conn,
                        handle,
                        result_json=json.dumps({"response_id": resp.id, "is_correct": is_correct}),
                    )
                self.conn.commit()
                return {"response_id": resp.id, "is_correct": is_correct, "is_duplicate": False}
            except LostClaimOwnershipError:
                self.conn.rollback()
                raise
            except Exception:
                self.conn.rollback()
                raise
        except LostClaimOwnershipError:
            raise
        except Exception:
            self._mark_claim_retryable(handle)
            raise

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------
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
        return {
            "learner_id": learner_id,
            "topic": learner.topic,
            "total_lessons": len(lessons),
            "total_feedback": len(all_feedback),
            "pending_review_lessons": sum(
                1
                for l in lessons
                if l.generation_status == "pending_review" and l.publication_state == "pending"
            ),
        }


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _tokens_or_none(value: Any) -> int | None:
    """Return an int token count, or None if the provider did not report usage."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _sanitize_error(message: str) -> str:
    """Bound and strip potential secrets from an error message before storage."""
    import re

    if not message:
        return ""
    sanitized = message
    for pattern, replacement in [
        (r"\b(sk-|ak-|pk-)[A-Za-z0-9]{16,}\b", "[REDACTED_KEY]"),
        (r"(?i)(api[_-]?key|password|secret|token|credential)\s*[:=]\s*\S+", r"\1=[REDACTED]"),
    ]:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized[:200]
