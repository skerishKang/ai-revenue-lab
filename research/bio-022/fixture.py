from __future__ import annotations

import hashlib
import json
import numpy as np

SEED = 20260826
N = 3000
N_FEATURES = 12


def generate_fixture():
    rng = np.random.default_rng(SEED)
    subgroup = rng.integers(0, 2, N)
    x = rng.normal(size=(N, N_FEATURES))
    linear = 2.2 * x[:, 0] - 1.5 * x[:, 1] + 0.8 * x[:, 2] + 0.6 * x[:, 3] * x[:, 4]
    noise = rng.normal(scale=np.where(subgroup == 0, 0.25, 4.0), size=N)
    y = (linear + noise > 0).astype(np.int64)
    x = np.column_stack([x, subgroup.astype(float)])

    order = np.arange(N)
    split_rng = np.random.default_rng(42)
    split_rng.shuffle(order)
    splits = {
        "overfit_train": order[:300],
        "regularized_train": order[:1400],
        "nonmember_pool": order[1800:2600],
        "control_pool": order[1400:],
    }
    return x, y, subgroup, splits


def _hash_parts(*parts):
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, np.ndarray):
            h.update(str(part.shape).encode())
            h.update(str(part.dtype).encode())
            h.update(part.tobytes())
        else:
            h.update(json.dumps(part, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def fixture_manifest():
    x, y, subgroup, splits = generate_fixture()
    return {
        "fixture_id": "HEALTHLIKE-SYNTH-001",
        "synthetic_only": True,
        "seed": SEED,
        "n": N,
        "n_features_including_subgroup": x.shape[1],
        "subgroup_semantics": "synthetic difficulty group only; not a real demographic attribute",
        "fingerprint_sha256": _hash_parts(
            x, y, subgroup, {k: v.tolist() for k, v in splits.items()}
        ),
        "splits": {
            k: {"n": int(len(v)), "index_sha256": _hash_parts(v)}
            for k, v in splits.items()
        },
    }
