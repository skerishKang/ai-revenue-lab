"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import tempfile
from typing import Generator

import pytest
import sqlite3

from app.db import apply_migrations
from app.config import Settings, reset_settings


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def test_settings(temp_db_path: str) -> Settings:
    reset_settings()
    return Settings(database_url=temp_db_path, environment="testing")


@pytest.fixture
def conn(test_settings: Settings) -> Generator[sqlite3.Connection, None, None]:
    apply_migrations(test_settings.database_url)
    conn = sqlite3.connect(test_settings.database_url)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


FIRST_LESSON_PLAN_FIXTURE = {
    "title": "변수와 값 이해하기",
    "sections": [
        {
            "section_id": "s1",
            "title": "변수란?",
            "description": "변수는 데이터를 저장하는盒子",
            "emphasis": "예제 중심",
        },
        {
            "section_id": "s2",
            "title": "값의 종류",
            "description": "숫자, 문자열, 불린 등",
            "emphasis": "실습 위주",
        },
    ],
}


SECOND_LESSON_PLAN_FIXTURE = {
    "title": "변수와 값 심화 - 피드백 반영",
    "sections": [
        {
            "section_id": "s1",
            "title": "변수 더 깊이 이해하기",
            "description": "이전보다 더 많은 예제 포함",
            "emphasis": "코드 먼저 제시",
        },
        {
            "section_id": "s2",
            "title": "값과 변수 활용",
            "description": "실전 예제 중심",
            "emphasis": "복습 문제 추가",
        },
    ],
}