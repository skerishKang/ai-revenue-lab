from __future__ import annotations

import hashlib
import pickle
import sklearn
from sklearn.ensemble import RandomForestClassifier

from fixture import hash_indices

MODEL_CONFIGS = {
    "overfit": {
        "n_estimators": 250,
        "max_depth": None,
        "min_samples_leaf": 1,
        "random_state": 1,
        "n_jobs": 1,
    },
    "regularized": {
        "n_estimators": 250,
        "max_depth": 5,
        "min_samples_leaf": 12,
        "random_state": 1,
        "n_jobs": 1,
    },
}


def train_conditions(x, y, splits):
    train_idx = splits["paired_train"]
    models = {}
    for name, config in MODEL_CONFIGS.items():
        model = RandomForestClassifier(**config)
        model.fit(x[train_idx], y[train_idx])
        models[name] = model
    return models


def fingerprint_model(name, model, train_idx):
    return {
        "sha256": hashlib.sha256(pickle.dumps(model, protocol=4)).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "model_type": type(model).__name__,
        "training_index_sha256": hash_indices(train_idx),
        "research_condition": name,
        "research_config": MODEL_CONFIGS[name],
    }
