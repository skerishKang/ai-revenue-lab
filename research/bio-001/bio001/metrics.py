from __future__ import annotations

import numpy as np


def _binary(array: np.ndarray) -> np.ndarray:
    return np.asarray(array).astype(bool)


def binary_metrics(prediction: np.ndarray, truth: np.ndarray) -> dict[str, float | int]:
    pred = _binary(prediction)
    target = _binary(truth)
    if pred.shape != target.shape:
        raise ValueError(f"shape mismatch: prediction={pred.shape}, truth={target.shape}")

    tp = int(np.logical_and(pred, target).sum())
    fp = int(np.logical_and(pred, np.logical_not(target)).sum())
    fn = int(np.logical_and(np.logical_not(pred), target).sum())
    tn = int(np.logical_and(np.logical_not(pred), np.logical_not(target)).sum())

    dice_den = 2 * tp + fp + fn
    iou_den = tp + fp + fn
    precision_den = tp + fp
    recall_den = tp + fn

    return {
        "dice": 1.0 if dice_den == 0 else (2.0 * tp) / dice_den,
        "iou": 1.0 if iou_den == 0 else tp / iou_den,
        "precision": 1.0 if precision_den == 0 and recall_den == 0 else (0.0 if precision_den == 0 else tp / precision_den),
        "recall": 1.0 if recall_den == 0 else tp / recall_den,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def region_agreement(prediction: np.ndarray, reference_region: np.ndarray) -> dict[str, float | bool]:
    pred = _binary(prediction)
    region = _binary(reference_region)
    if pred.shape != region.shape:
        raise ValueError(f"shape mismatch: prediction={pred.shape}, region={region.shape}")

    region_pixels = int(region.sum())
    if region_pixels == 0:
        return {"region_hit": False, "region_recall": 0.0, "prediction_in_region": 0.0}

    overlap = int(np.logical_and(pred, region).sum())
    pred_pixels = int(pred.sum())
    return {
        "region_hit": overlap > 0,
        "region_recall": overlap / region_pixels,
        "prediction_in_region": 0.0 if pred_pixels == 0 else overlap / pred_pixels,
    }
