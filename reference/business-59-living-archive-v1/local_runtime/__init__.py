"""Bounded local-only import and exact-search slice for Business 59.

Two layers are exposed:

* :class:`LocalSourceIndex` — the original in-memory prototype slice
  (``source_index.py``), unchanged and still fully supported;
* :class:`DurableSourceIndex` — the additive SQLite-backed durable runtime
  (``persistence.py`` + ``lifecycle.py`` + ``durable_index.py``) that survives
  process restart and separates original / derived / user storage.
"""

from .durable_index import (
    ANCHOR_TEXT_DRIFT,
    Annotation,
    AnchorResolution,
    Bookmark,
    DEFAULT_IMPLEMENTATION_VERSION,
    DERIVED_ANCHOR_MISSING,
    DERIVED_INDEX_MISSING,
    DurableImportResult,
    DurableSourceIndex,
    ReadingPosition,
)
from .lifecycle import (
    DEFERRED_STAGE_NAMES,
    IMPORT_IMPLEMENTATION_VERSION,
    STAGE_NAMES,
    ImportRun,
    ImportStage,
    RunKind,
    RunStatus,
    StageEvent,
    StageRecorder,
    StageStatus,
)
from .persistence import ArchiveError, StorageFailure, UnsafeSourcePath
from .source_index import (
    ImportResult,
    ImportStatus,
    LocalSourceIndex,
    SearchResult,
    SourceRecord,
)

__all__ = [
    # in-memory slice (unchanged)
    "ImportResult",
    "ImportStatus",
    "LocalSourceIndex",
    "SearchResult",
    "SourceRecord",
    # durable runtime
    "ANCHOR_TEXT_DRIFT",
    "Annotation",
    "AnchorResolution",
    "ArchiveError",
    "Bookmark",
    "DEFAULT_IMPLEMENTATION_VERSION",
    "DEFERRED_STAGE_NAMES",
    "DERIVED_ANCHOR_MISSING",
    "DERIVED_INDEX_MISSING",
    "DurableImportResult",
    "DurableSourceIndex",
    "IMPORT_IMPLEMENTATION_VERSION",
    "ImportRun",
    "ImportStage",
    "ReadingPosition",
    "RunKind",
    "RunStatus",
    "STAGE_NAMES",
    "StageEvent",
    "StageRecorder",
    "StageStatus",
    "StorageFailure",
    "UnsafeSourcePath",
]
