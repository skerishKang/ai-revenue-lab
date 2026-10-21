"""ERP item-master pilot (#5447).

The package turns a supplier catalog into an ERP import file. It reads CSV and
Excel sources, normalizes the item-master fields, detects duplicate items,
marks the records that still need a person and writes the import files.

It does not own an ERP, a model provider or a credential. The import schema of
a concrete ERP lives in :mod:`app.erp_profile` together with the evidence that
backs each field.
"""

from __future__ import annotations

from .contracts import (
    CANONICAL_FIELDS,
    ConfirmationStatus,
    DuplicateKind,
    FieldOrigin,
    FieldValue,
    ItemMasterError,
    ItemRecord,
    ReviewStatus,
)
from .erp_profile import (
    ErpImportProfile,
    all_profiles,
    ecount_api_candidate_profile,
    ecount_excel_profile,
    generic_profile,
    profile_by_id,
)
from .pipeline import PipelineReport, run_pipeline

__all__ = (
    "CANONICAL_FIELDS",
    "ConfirmationStatus",
    "DuplicateKind",
    "ErpImportProfile",
    "FieldOrigin",
    "FieldValue",
    "ItemMasterError",
    "ItemRecord",
    "PipelineReport",
    "ReviewStatus",
    "all_profiles",
    "ecount_api_candidate_profile",
    "ecount_excel_profile",
    "generic_profile",
    "profile_by_id",
    "run_pipeline",
)
