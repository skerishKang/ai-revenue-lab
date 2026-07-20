"""Pipeline error hierarchy for Living Travel."""

from __future__ import annotations


class PipelineError(Exception):
    pass


class ValidationError(PipelineError):
    pass


class ReferenceError_(PipelineError):
    pass


class MarkupError(PipelineError):
    pass


class ProviderError(PipelineError):
    pass


class SchemaMismatchError(PipelineError):
    pass
