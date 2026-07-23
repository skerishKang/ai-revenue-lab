"""Application services for the Korean AI Platform (Business 14).

The service layer owns transition-unit transaction boundaries:

    route -> application service -> repository / transaction
                                      -> engine pure state transition
                                      -> DB persistence

The engine stays pure (domain transitions + artifact creation). Repositories
own SQL + hydration. The service loads, validates via the engine, mutates, and
persists each transition atomically. On failure, memory and DB never diverge
and no success redirect is produced.

Two backends share one interface:
- ``InMemoryTaskService`` wraps the in-memory ``Store`` (test/demo seam);
- ``SqliteTaskService`` wraps product-local SQLite repositories.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from app import engine, mock_data
from app.db import PersistenceError, get_connection
from app.domain import ModelSpec, Project, Task
from app.repositories import (
    SettingsRepository,
    TaskRepository,
    is_seeded,
    mark_seeded,
)
from app.store import (
    ByokState,
    SecuritySettings,
    Store,
    parse_cost_limit,
    validate_and_build_task,
)


class TaskNotFound(Exception):
    pass


def build_settings_from_form(
    current: SecuritySettings,
    models: dict[str, ModelSpec],
    form: dict,
) -> tuple[SecuritySettings | None, dict[str, str]]:
    """Build a new SecuritySettings from a submitted form (pure).

    Validation is atomic: if any input is invalid, ``(None, errors)`` is
    returned and nothing is changed. ``block_push_without_approval`` is always
    forced true (mandatory invariant). A blank BYOK key preserves the existing
    registration; unregistration requires an explicit checkbox.
    """
    parsed_limit, limit_error = parse_cost_limit(str(form.get("project_cost_limit_krw") or ""))
    if limit_error is not None:
        return None, {"project_cost_limit_krw": limit_error}

    new = current.model_copy(deep=True)
    new.domestic_first = form.get("domestic_first") == "on"
    new.allow_external = form.get("allow_external") == "on"
    new.block_on_secret = form.get("block_on_secret") == "on"
    new.block_push_without_approval = True  # mandatory, never user-disableable
    if parsed_limit is not None:
        new.project_cost_limit_krw = parsed_limit

    for model in models.values():
        if not model.requires_byok:
            continue
        state = new.byok.setdefault(model.id, ByokState())
        raw = str(form.get(f"apikey_{model.id}", "") or "")
        if raw.strip():
            state.registered = True  # presence only; raw value discarded
        if form.get(f"apikey_unregister_{model.id}") == "on":
            state.registered = False  # explicit unregistration only

    return new, {}


class BaseTaskService:
    persistence_kind = "base"
    persistence_label = ""

    def __init__(self) -> None:
        self.models: dict[str, ModelSpec] = mock_data.models_by_id()
        self.projects: dict[str, Project] = mock_data.projects_by_id()

    # Shared pure helpers -------------------------------------------------
    def data_regions(self, task: Task) -> dict:
        return engine.data_regions(task, self.models)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self.list_tasks():
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return counts

    def monthly_estimated_krw(self) -> float:
        total = 0.0
        for task in self.list_tasks():
            if task.run is not None:
                total += task.run.cost_total_krw
        return round(total, 2)

    # Interface (implemented by backends) ---------------------------------
    def list_tasks(self) -> list[Task]:
        raise NotImplementedError

    def get_task(self, task_id: str) -> Task | None:
        raise NotImplementedError

    def create_task(self, form: dict) -> tuple[Task | None, dict[str, str]]:
        raise NotImplementedError

    def run_task(self, task_id: str) -> Task:
        raise NotImplementedError

    def approve_task(self, task_id: str, approver: str) -> Task:
        raise NotImplementedError

    def request_rework(self, task_id: str, reason: str) -> Task:
        raise NotImplementedError

    def reject_task(self, task_id: str, reason: str) -> Task:
        raise NotImplementedError

    def get_settings(self) -> SecuritySettings:
        raise NotImplementedError

    def save_settings(self, form: dict) -> tuple[bool, dict[str, str]]:
        raise NotImplementedError


class InMemoryTaskService(BaseTaskService):
    """Test/demo seam wrapping the in-memory Store (no persistence)."""

    persistence_kind = "memory"
    persistence_label = "인메모리 Demo · 재시작 시 초기화"

    def __init__(self, store: Store) -> None:
        super().__init__()
        self._store = store
        # Catalogs come from the store so injected fixtures stay authoritative.
        self.models = store.models
        self.projects = store.projects

    def list_tasks(self) -> list[Task]:
        return self._store.list_tasks()

    def get_task(self, task_id: str) -> Task | None:
        return self._store.get_task(task_id)

    def create_task(self, form: dict) -> tuple[Task | None, dict[str, str]]:
        from app.store import create_task as store_create_task

        return store_create_task(self._store, form)

    def _load(self, task_id: str) -> Task:
        task = self._store.get_task(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        return task

    def run_task(self, task_id: str) -> Task:
        task = self._load(task_id)
        engine.run_task(task, self.models)  # mutates the stored object in place
        return task

    def approve_task(self, task_id: str, approver: str) -> Task:
        task = self._load(task_id)
        engine.approve_task(task, approver)
        return task

    def request_rework(self, task_id: str, reason: str) -> Task:
        task = self._load(task_id)
        engine.request_rework(task, reason, self.models)
        return task

    def reject_task(self, task_id: str, reason: str) -> Task:
        task = self._load(task_id)
        engine.reject_task(task, reason)
        return task

    def get_settings(self) -> SecuritySettings:
        return self._store.settings

    def save_settings(self, form: dict) -> tuple[bool, dict[str, str]]:
        new_settings, errors = build_settings_from_form(
            self._store.settings, self.models, form
        )
        if new_settings is None:
            return False, errors
        # Mutate the existing settings object in place so external references
        # (e.g. tests holding store.settings) observe the update.
        current = self._store.settings
        current.domestic_first = new_settings.domestic_first
        current.allow_external = new_settings.allow_external
        current.block_on_secret = new_settings.block_on_secret
        current.project_cost_limit_krw = new_settings.project_cost_limit_krw
        current.block_push_without_approval = new_settings.block_push_without_approval
        current.byok = new_settings.byok
        return True, {}


class SqliteTaskService(BaseTaskService):
    """Product-local SQLite-backed service with explicit write transactions."""

    persistence_kind = "sqlite"
    persistence_label = "로컬 SQLite 저장 · 단일 프로세스"

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._tasks = TaskRepository()
        self._settings = SettingsRepository()

    @contextmanager
    def _tx(self):
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def _read(self):
        conn = get_connection(self._db_path)
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self, seed: bool = True) -> None:
        """Run migrations and (optionally) seed demo data once on an empty DB.

        ``seed=False`` applies migrations but leaves the database empty (test
        seam). Seeding happens only on a truly empty database and only once;
        it is tracked by a product-local ``seed_meta`` record.
        """
        from pathlib import Path

        from app.db import apply_migrations

        conn = get_connection(self._db_path)
        try:
            migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")
            apply_migrations(conn, migrations_dir)
            conn.execute("BEGIN IMMEDIATE")
            try:
                if seed and not is_seeded(conn) and self._tasks.count_tasks(conn) == 0:
                    for task in mock_data.build_seed_tasks():
                        self._tasks.save_task(conn, task)
                mark_seeded(conn)
                conn.execute("COMMIT")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    def list_tasks(self) -> list[Task]:
        try:
            with self._read() as conn:
                return self._tasks.load_all_tasks(conn)
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def get_task(self, task_id: str) -> Task | None:
        try:
            with self._read() as conn:
                return self._tasks.load_task(conn, task_id)
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def run_history(self, task_id: str):
        try:
            with self._read() as conn:
                return self._tasks.load_run_history(conn, task_id)
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def create_task(self, form: dict) -> tuple[Task | None, dict[str, str]]:
        settings = self.get_settings()
        try:
            with self._tx() as conn:
                task, errors = validate_and_build_task(
                    self.models,
                    self.projects,
                    settings,
                    form,
                    lambda: self._tasks.next_task_id(conn),
                )
                if task is None:
                    return None, errors
                self._tasks.save_task(conn, task)
                return task, {}
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def _transition(self, task_id: str, mutate):
        try:
            with self._tx() as conn:
                task = self._tasks.load_task(conn, task_id)
                if task is None:
                    raise TaskNotFound(task_id)
                mutate(task)  # engine pure transition; may raise IllegalTransition
                self._tasks.save_task(conn, task)
                return task
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def run_task(self, task_id: str) -> Task:
        return self._transition(task_id, lambda t: engine.run_task(t, self.models))

    def approve_task(self, task_id: str, approver: str) -> Task:
        return self._transition(task_id, lambda t: engine.approve_task(t, approver))

    def request_rework(self, task_id: str, reason: str) -> Task:
        return self._transition(
            task_id, lambda t: engine.request_rework(t, reason, self.models)
        )

    def reject_task(self, task_id: str, reason: str) -> Task:
        return self._transition(task_id, lambda t: engine.reject_task(t, reason))

    def get_settings(self) -> SecuritySettings:
        try:
            with self._read() as conn:
                return self._settings.load_settings(conn)
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc

    def save_settings(self, form: dict) -> tuple[bool, dict[str, str]]:
        try:
            with self._tx() as conn:
                current = self._settings.load_settings(conn)
                new_settings, errors = build_settings_from_form(
                    current, self.models, form
                )
                if new_settings is None:
                    return False, errors
                self._settings.save_settings(conn, new_settings)
                return True, {}
        except sqlite3.Error as exc:
            raise PersistenceError(exc) from exc
