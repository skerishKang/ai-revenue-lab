from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any

import numpy as np

from .classical import classical_segment
from .local_data import binarize_vein_mask, read_grayscale, resolve_local_path
from .metrics import binary_metrics, region_agreement
from .provenance import load_manifest


def _mean(records: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in records if row.get(key) is not None]
    return None if not values else float(np.mean(values))


def benchmark_dataset(
    dataset_csv: Path,
    manifest_path: Path,
    *,
    image_column: str,
    mask_column: str,
    sample_id_column: str | None = None,
    nurse_region_column: str | None = None,
    subgroup_columns: tuple[str, ...] = (),
    vein_label: int = 2,
    max_samples: int | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    if not dataset_csv.exists():
        raise FileNotFoundError(dataset_csv)

    root = dataset_csv.parent
    per_sample: list[dict[str, Any]] = []

    with dataset_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("dataset CSV has no header")

        required_columns = {image_column, mask_column}
        if sample_id_column:
            required_columns.add(sample_id_column)
        if nurse_region_column:
            required_columns.add(nurse_region_column)
        required_columns.update(subgroup_columns)
        missing = sorted(required_columns.difference(reader.fieldnames))
        if missing:
            raise ValueError(f"dataset CSV missing columns: {', '.join(missing)}")

        for index, row in enumerate(reader):
            if max_samples is not None and len(per_sample) >= max_samples:
                break

            image_path = resolve_local_path(root, row[image_column])
            mask_path = resolve_local_path(root, row[mask_column])
            gray = read_grayscale(image_path)
            truth = binarize_vein_mask(read_grayscale(mask_path), vein_label=vein_label)
            if gray.shape != truth.shape:
                raise ValueError(
                    f"image/mask shape mismatch for row {index}: {gray.shape} vs {truth.shape}"
                )

            started = time.perf_counter()
            result = classical_segment(gray)
            latency_ms = (time.perf_counter() - started) * 1000.0
            metrics = binary_metrics(result.mask, truth)

            sample: dict[str, Any] = {
                "sample_id": row[sample_id_column] if sample_id_column else str(index),
                "dice": metrics["dice"],
                "iou": metrics["iou"],
                "precision": metrics["precision"],
                "recall": metrics["recall"],
                "latency_ms": latency_ms,
                "confidence": result.confidence,
                "image_quality": result.image_quality,
                "predicted_fraction": result.predicted_fraction,
                "abstain": result.abstain,
            }

            if nurse_region_column and row.get(nurse_region_column, "").strip():
                nurse_path = resolve_local_path(root, row[nurse_region_column])
                nurse_region = read_grayscale(nurse_path) > 0
                if nurse_region.shape != result.mask.shape:
                    raise ValueError(
                        f"nurse-region shape mismatch for row {index}: "
                        f"{nurse_region.shape} vs {result.mask.shape}"
                    )
                sample.update(region_agreement(result.mask, nurse_region))

            for column in subgroup_columns:
                sample[f"subgroup_{column}"] = row[column]
            per_sample.append(sample)

    if not per_sample:
        raise ValueError("dataset produced zero benchmark samples")

    summary: dict[str, Any] = {
        "samples": len(per_sample),
        "mean_dice": _mean(per_sample, "dice"),
        "mean_iou": _mean(per_sample, "iou"),
        "mean_precision": _mean(per_sample, "precision"),
        "mean_recall": _mean(per_sample, "recall"),
        "mean_latency_ms": _mean(per_sample, "latency_ms"),
        "mean_confidence": _mean(per_sample, "confidence"),
        "abstention_rate": float(np.mean([bool(row["abstain"]) for row in per_sample])),
    }

    region_rows = [row for row in per_sample if "region_hit" in row]
    if region_rows:
        summary["mean_region_recall"] = _mean(region_rows, "region_recall")
        summary["region_hit_rate"] = float(
            np.mean([bool(row["region_hit"]) for row in region_rows])
        )

    return {
        "benchmark": "BIO-001 classical baseline",
        "evidence_status": "implementation_or_local_research_only_not_clinical_evidence",
        "manifest": manifest,
        "summary": summary,
        "per_sample": per_sample,
    }
