from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def resolve_local_path(root: Path, raw: str) -> Path:
    value = raw.strip()
    if not value:
        raise ValueError("empty local data path")
    if "://" in value:
        raise ValueError("network URLs are not accepted by the benchmark loader")
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else root / candidate


def read_grayscale(path: Path) -> np.ndarray:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"unable to decode image: {path}")
    return image


def binarize_vein_mask(mask: np.ndarray, vein_label: int = 2) -> np.ndarray:
    values = np.unique(mask)
    if vein_label in values:
        return mask == vein_label
    value_set = set(int(v) for v in values.tolist())
    if value_set.issubset({0, 1}) or value_set.issubset({0, 255}):
        return mask > 0
    raise ValueError(
        f"vein label {vein_label} not present in mask values {sorted(value_set)[:12]}"
    )
