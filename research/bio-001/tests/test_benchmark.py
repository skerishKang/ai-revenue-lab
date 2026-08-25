import csv
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from bio001 import (
    benchmark_dataset,
    binary_metrics,
    classical_segment,
    load_manifest,
    region_agreement,
)


def test_binary_metrics_perfect_and_disjoint():
    truth = np.array([[1, 0], [0, 1]], dtype=bool)
    perfect = binary_metrics(truth, truth)
    assert perfect["dice"] == pytest.approx(1.0)
    assert perfect["iou"] == pytest.approx(1.0)

    disjoint = binary_metrics(np.logical_not(truth), truth)
    assert disjoint["dice"] == pytest.approx(0.0)
    assert disjoint["iou"] == pytest.approx(0.0)


def test_region_agreement_reports_hit_and_recall():
    pred = np.zeros((10, 10), dtype=bool)
    pred[4:7, 4:7] = True
    region = np.zeros((10, 10), dtype=bool)
    region[5:8, 5:8] = True

    result = region_agreement(pred, region)
    assert result["region_hit"] is True
    assert result["region_recall"] == pytest.approx(4 / 9)


def test_manifest_requires_evidence_ready_license(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "dataset_name": "fixture",
                "upstream_url": "https://example.test/data",
                "data_license": "UNKNOWN",
                "permitted_use": "research",
                "redistribution_allowed": False,
                "version": "1",
                "fingerprint": "sha256:fixture",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not evidence-ready"):
        load_manifest(manifest)


def test_classical_segment_is_binary_and_bounded():
    image = np.full((128, 128), 210, dtype=np.uint8)
    cv2.line(image, (10, 64), (118, 64), 70, 5)
    cv2.line(image, (40, 20), (80, 110), 90, 3)
    image = cv2.GaussianBlur(image, (5, 5), 0)

    result = classical_segment(image, min_component_area=5)
    assert result.mask.shape == image.shape
    assert result.mask.dtype == bool
    assert result.mask.any()
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.image_quality <= 1.0
    assert 0.0 <= result.predicted_fraction <= 1.0


def test_end_to_end_local_fixture(tmp_path: Path):
    image = np.full((96, 96), 220, dtype=np.uint8)
    cv2.line(image, (8, 45), (88, 45), 55, 5)
    image = cv2.GaussianBlur(image, (3, 3), 0)

    mask = np.zeros_like(image)
    cv2.line(mask, (8, 45), (88, 45), 2, 5)

    nurse = np.zeros_like(image)
    nurse[35:56, 40:60] = 255

    cv2.imwrite(str(tmp_path / "image.png"), image)
    cv2.imwrite(str(tmp_path / "mask.png"), mask)
    cv2.imwrite(str(tmp_path / "nurse.png"), nurse)

    with (tmp_path / "dataset.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "image", "mask", "nurse", "complexion"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "fixture-1",
                "image": "image.png",
                "mask": "mask.png",
                "nurse": "nurse.png",
                "complexion": "synthetic",
            }
        )

    manifest = {
        "dataset_name": "synthetic-fixture",
        "upstream_url": "https://example.test/synthetic-fixture",
        "data_license": "CC0-1.0",
        "permitted_use": "test-only synthetic fixture",
        "redistribution_allowed": True,
        "version": "1",
        "fingerprint": "sha256:synthetic-fixture",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = benchmark_dataset(
        tmp_path / "dataset.csv",
        tmp_path / "manifest.json",
        image_column="image",
        mask_column="mask",
        sample_id_column="id",
        nurse_region_column="nurse",
        subgroup_columns=("complexion",),
        vein_label=2,
    )

    assert report["summary"]["samples"] == 1
    assert 0.0 <= report["summary"]["mean_dice"] <= 1.0
    assert report["per_sample"][0]["sample_id"] == "fixture-1"
    assert report["per_sample"][0]["subgroup_complexion"] == "synthetic"
