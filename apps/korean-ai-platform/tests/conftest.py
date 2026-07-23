from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import mock_data
from app.domain import BranchMode, ExternalPolicy, Task
from app.factory import create_app
from app.store import Store


@pytest.fixture()
def models():
    return mock_data.models_by_id()


@pytest.fixture()
def store():
    return Store(seed=False)


@pytest.fixture()
def seeded_store():
    return Store(seed=True)


@pytest.fixture()
def app(store):
    return create_app(store=store)


@pytest.fixture()
def client(app):
    return TestClient(app)


def make_task(store: Store, **overrides) -> Task:
    defaults = dict(
        id=store.next_id(),
        title="주문 생성 시 재고 검증 추가",
        instruction="재고가 부족하면 주문이 실패하도록 검증 로직을 추가해 주세요.",
        project_id="commerce-backend",
        worker_model_id="openai-gpt",
        validator_model_id="anthropic-claude",
        allowed_paths=["app/", "tests/"],
        denied_paths=["migrations/"],
        cost_limit_krw=5000.0,
        external_policy=ExternalPolicy.ALLOW,
        branch_mode=BranchMode.AUTO,
    )
    defaults.update(overrides)
    task = Task(**defaults)
    store.tasks[task.id] = task
    return task


CREATE_FORM = {
    "title": "결제 취소 API 개선",
    "instruction": "결제 취소 실패 시 오류 메시지를 개선해 주세요.",
    "project_id": "commerce-backend",
    "worker_model_id": "domestic-open",
    "validator_model_id": "anthropic-claude",
    "allowed_paths": "app/, tests/",
    "denied_paths": "migrations/",
    "cost_limit_krw": "3000",
    "external_policy": "allow",
    "branch_mode": "auto",
}
