"""BIO-001 education/research benchmark utilities."""

from .classical import SegmentationResult, classical_segment
from .dataset import benchmark_dataset, load_manifest
from .metrics import binary_metrics, region_agreement

__all__ = [
    "SegmentationResult",
    "classical_segment",
    "benchmark_dataset",
    "load_manifest",
    "binary_metrics",
    "region_agreement",
]
