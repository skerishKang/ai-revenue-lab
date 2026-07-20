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
    def __init__(self, feedback_id: str, learner_id: str) -> None:
        self.feedback_id = feedback_id
        self.learner_id = learner_id
        super().__init__(f"Feedback {feedback_id} does not belong to learner {learner_id}")


class GenerationError(LessonPipelineError):
    pass


class RetryExhaustedError(LessonPipelineError):
    def __init__(self, task_type: str, attempts: int) -> None:
        self.task_type = task_type
        self.attempts = attempts
        super().__init__(f"Max retries ({attempts}) exhausted for {task_type}")