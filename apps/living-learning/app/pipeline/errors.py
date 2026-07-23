"""Pipeline service errors."""


class LessonPipelineError(Exception):
    pass


class PrerequisiteNotMetError(LessonPipelineError):
    def __init__(self, concept_id: str, missing: list[str]) -> None:
        self.concept_id = concept_id
        self.missing = missing
        super().__init__(f"Prerequisites not met for {concept_id}: {missing}")


class FeedbackAlreadyAppliedError(LessonPipelineError):
    def __init__(self, feedback_id: str) -> None:
        self.feedback_id = feedback_id
        super().__init__(f"Feedback {feedback_id} already applied")


class ForeignFeedbackError(LessonPipelineError):
    def __init__(self, resource_id: str, learner_id: str) -> None:
        self.resource_id = resource_id
        self.learner_id = learner_id
        super().__init__(f"Resource {resource_id} does not belong to learner {learner_id}")


class GenerationError(LessonPipelineError):
    pass


class RetryExhaustedError(LessonPipelineError):
    def __init__(self, task_type: str, attempts: int) -> None:
        self.task_type = task_type
        self.attempts = attempts
        super().__init__(f"Max retries ({attempts}) exhausted for {task_type}")


class ContentValidationError(LessonPipelineError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(f"Content validation failed: {issues}")


class AdaptationNotChangedError(LessonPipelineError):
    def __init__(self, details: dict) -> None:
        self.details = details
        super().__init__(f"Adaptation did not make requested changes: {details}")


class ComprehensionRequiredError(LessonPipelineError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class LearnerInactiveError(LessonPipelineError):
    def __init__(self, learner_id: str, status: str) -> None:
        self.learner_id = learner_id
        self.status = status
        super().__init__(f"Learner {learner_id} is inactive (status: {status})")


class UnsafeContentError(LessonPipelineError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__(f"Unsafe content detected: {issues}")

class ConflictingAnswerError(LessonPipelineError):
    def __init__(self, exercise_id: str) -> None:
        self.exercise_id = exercise_id
        super().__init__(f"Conflicting answer for exercise {exercise_id}")


class CredentialRequestError(LessonPipelineError):
    pass


class MedicalDisabilityInferenceError(LessonPipelineError):
    pass


class FabricatedFactError(LessonPipelineError):
    pass


class PackageInstallError(LessonPipelineError):
    pass


class ExpectedAnswerMismatchError(LessonPipelineError):
    pass


class NonRetryableError(LessonPipelineError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"Non-retryable error: {message}")


class ConcurrentOperationError(LessonPipelineError):
    """Raised when an idempotency claim is held by another in-flight owner."""

    def __init__(self, operation_key: str) -> None:
        self.operation_key = operation_key
        super().__init__("A concurrent request for this operation is in progress")


class OperationTerminalError(LessonPipelineError):
    """Raised when an operation is blocked by a terminal (non-retryable) failure."""

    def __init__(self, operation_key: str) -> None:
        self.operation_key = operation_key
        super().__init__("This operation previously failed terminally and will not be retried")