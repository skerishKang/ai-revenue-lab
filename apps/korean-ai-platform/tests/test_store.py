from app.domain import TaskStatus
from app.store import SecuritySettings, Store, create_task
from tests.conftest import CREATE_FORM


def test_create_task_success(store):
    task, errors = create_task(store, dict(CREATE_FORM))
    assert errors == {}
    assert task is not None
    assert task.status == TaskStatus.READY
    assert task.id in store.tasks
    assert task.allowed_paths == ["app/", "tests/"]


def test_create_task_falls_back_to_project_defaults(store):
    form = dict(CREATE_FORM)
    form["allowed_paths"] = ""
    form["denied_paths"] = ""
    task, errors = create_task(store, form)
    assert errors == {}
    project = store.projects[task.project_id]
    assert task.allowed_paths == project.default_allowed
    assert task.denied_paths == project.default_denied


def test_create_task_requires_fields(store):
    form = dict(CREATE_FORM)
    form["title"] = ""
    form["instruction"] = ""
    form["project_id"] = ""
    task, errors = create_task(store, form)
    assert task is None
    assert "title" in errors
    assert "instruction" in errors
    assert "project_id" in errors


def test_create_task_rejects_bad_cost(store):
    form = dict(CREATE_FORM)
    form["cost_limit_krw"] = "abc"
    task, errors = create_task(store, form)
    assert task is None
    assert "cost_limit_krw" in errors


def test_status_counts_and_monthly_cost(seeded_store):
    counts = seeded_store.status_counts()
    assert counts.get("completed", 0) >= 1
    assert counts.get("awaiting_approval", 0) >= 1
    assert counts.get("rework", 0) >= 1
    assert seeded_store.monthly_estimated_krw() >= 0


def test_next_id_is_unique(store):
    first = store.next_id()
    second = store.next_id()
    assert first != second


def test_security_settings_store_no_key_material(store):
    fields = set(SecuritySettings.model_fields.keys())
    assert "api_key" not in fields
    assert "apikey" not in fields
