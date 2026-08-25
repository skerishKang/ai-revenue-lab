from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class SegmentationResult:
    mask: np.ndarray
    response: np.ndarray
    confidence: float
    image_quality: float
    predicted_fraction: float
    abstain: bool


def _remove_small_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    binary = (mask > 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cleaned = np.zeros_like(binary)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            cleaned[labels == label] = 1
    return cleaned.astype(bool)


def classical_segment(gray: np.ndarray, min_component_area: int = 20) -> SegmentationResult:
    """Deterministic comparison floor; not a clinical or product model."""
    image = np.asarray(gray)
    if image.ndim != 2:
        raise ValueError("classical_segment expects a 2D grayscale image")
    if image.size == 0:
        raise ValueError("empty image")
    if image.dtype != np.uint8:
        image = cv2.normalize(image, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(image)

    responses = []
    for size in (9, 15, 21):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        responses.append(cv2.morphologyEx(enhanced, cv2.MORPH_BLACKHAT, kernel))
    response = np.maximum.reduce(responses)
    response = cv2.GaussianBlur(response, (5, 5), 0)

    _, thresholded = cv2.threshold(response, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresholded = cv2.morphologyEx(
        thresholded,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    thresholded = cv2.morphologyEx(
        thresholded,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    )
    mask = _remove_small_components(thresholded, max(1, int(min_component_area)))

    predicted_fraction = float(mask.mean())
    confidence = float(np.mean(response[mask]) / 255.0) if mask.any() else 0.0
    image_quality = float(np.clip(np.std(enhanced) / 64.0, 0.0, 1.0))
    abstain = bool(
        not mask.any()
        or predicted_fraction < 0.0005
        or predicted_fraction > 0.35
        or confidence < 0.03
        or image_quality < 0.05
    )
    return SegmentationResult(
        mask=mask,
        response=response,
        confidence=confidence,
        image_quality=image_quality,
        predicted_fraction=predicted_fraction,
        abstain=abstain,
    )
