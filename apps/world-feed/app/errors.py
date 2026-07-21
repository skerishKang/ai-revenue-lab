"""Domain errors for the World Feed service and API mapping."""


class BriefGenerationError(RuntimeError):
    def __init__(self, run_id: str, message: str):
        self.run_id = run_id
        self.message = message
        super().__init__(message)


class NoEligibleEventsError(RuntimeError):
    pass


class BriefUnchangedError(RuntimeError):
    pass


class AlreadyAppliedFeedbackError(RuntimeError):
    pass


class ForeignFeedbackError(RuntimeError):
    pass


class MismatchedPriorBriefError(RuntimeError):
    pass


class FirstBriefMissingError(RuntimeError):
    pass


class SourceGroundingError(RuntimeError):
    pass


class EvidenceValidationError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass


class UsageAccountingError(RuntimeError):
    pass
