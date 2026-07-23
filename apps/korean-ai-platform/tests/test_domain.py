from app.domain import (
    ChangedFile,
    evaluate_path_policy,
    model_cost_krw,
    path_matches,
)


def test_path_matches_directory_prefix():
    assert path_matches("app/", "app/services/x.py")
    assert path_matches("app/", "app")
    assert not path_matches("app/", "application/x.py")


def test_path_matches_exact_file():
    assert path_matches("app/config.py", "app/config.py")
    assert not path_matches("app/config.py", "app/config.py.bak")


def test_path_matches_blank_pattern_never_matches():
    assert not path_matches("", "app/x.py")
    assert not path_matches("   ", "app/x.py")


def _files(*paths):
    return [
        ChangedFile(path=p, additions=1, deletions=0, language="python", diff="")
        for p in paths
    ]


def test_policy_no_rules_no_violations():
    assert evaluate_path_policy(_files("app/x.py"), [], []) == []


def test_policy_denied_path_flagged():
    violations = evaluate_path_policy(
        _files("migrations/001.sql"), ["app/", "tests/"], ["migrations/"]
    )
    assert any("수정 금지 경로" in v for v in violations)


def test_policy_outside_allowed_flagged():
    violations = evaluate_path_policy(
        _files("tests/test_a.py", "docs/readme.md"), ["app/", "tests/"], []
    )
    assert any("docs/readme.md" in v for v in violations)
    assert not any("tests/test_a.py" in v for v in violations)


def test_model_cost_krw_calculation():
    from app.mock_data import models_by_id

    models = models_by_id()
    cost = model_cost_krw(models["openai-gpt"], 1000, 1000)
    assert cost == 6.0 + 24.0


def test_model_cost_krw_free_local_model():
    from app.mock_data import models_by_id

    models = models_by_id()
    assert model_cost_krw(models["domestic-open"], 5000, 5000) == 0.0
