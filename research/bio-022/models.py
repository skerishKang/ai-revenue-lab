from __future__ import annotations

import hashlib
import pickle
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def train_conditions(x, y, splits):
    overfit = RandomForestClassifier(
        n_estimators=250,
        max_depth=None,
        min_samples_leaf=1,
        random_state=1,
        n_jobs=1,
    )
    overfit.fit(x[splits["overfit_train"]], y[splits["overfit_train"]])

    regularized = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.15, max_iter=1000, random_state=1),
    )
    regularized.fit(x[splits["regularized_train"]], y[splits["regularized_train"]])
    return {"overfit": overfit, "regularized": regularized}


def fingerprint_model(model):
    return {
        "sha256": hashlib.sha256(pickle.dumps(model, protocol=4)).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "model_type": type(model).__name__,
    }
