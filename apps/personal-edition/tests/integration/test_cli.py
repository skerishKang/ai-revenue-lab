import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.config import Settings
from app.db import apply_migrations, get_connection
from app.db_runtime import SqliteRuntimeConnection
from app import participant_repository as repo


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def initialized_db(db_path):
    conn = get_connection(db_path)
    apply_migrations(conn, "migrations")
    conn.close()
    return db_path


@pytest.fixture
def venv_python():
    return sys.executable


class TestProvisionParticipant:
    def test_provision_success(self, initialized_db, venv_python):
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.provision_participant",
                "cli-p1", "CLI User",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "cli-p1" in result.stdout
        assert "ONE-TIME TOKEN" in result.stdout

    def test_provision_with_language(self, initialized_db, venv_python):
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.provision_participant",
                "cli-p2", "English User",
                "--language", "en",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "cli-p2" in result.stdout

    def test_provision_duplicate_fails(self, initialized_db, venv_python):
        subprocess.run(
            [
                venv_python, "-m", "scripts.provision_participant",
                "cli-dup", "First",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.provision_participant",
                "cli-dup", "Second",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 1

    def test_token_not_in_db(self, initialized_db, venv_python):
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.provision_participant",
                "cli-tok", "Token Test",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0

        token_line = [
            line for line in result.stdout.splitlines()
            if line and "ONE-TIME" not in line and "token" not in line.lower()
            and "Participant" not in line and "Display" not in line
            and "Language" not in line and "Status" not in line
            and "Created" not in line
        ]

        conn = get_connection(initialized_db)
        row = conn.execute(
            "SELECT access_token_hash FROM participants WHERE id = ?",
            ("cli-tok",),
        ).fetchone()
        conn.close()
        assert row is not None
        assert len(row["access_token_hash"]) == 64


class TestDeleteParticipant:
    def test_delete_success(self, initialized_db, venv_python):
        conn = get_connection(initialized_db)
        repo.create_participant(
        SqliteRuntimeConnection(conn),
            participant_id="del-p1",
            display_name="To Delete",
        )
        conn.close()

        result = subprocess.run(
            [
                venv_python, "-m", "scripts.delete_participant",
                "del-p1",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "deleted" in result.stdout.lower()

    def test_delete_nonexistent_fails(self, initialized_db, venv_python):
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.delete_participant",
                "no-such-p",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 1

    def test_delete_revokes_token(self, initialized_db, venv_python):
        conn = get_connection(initialized_db)
        prov = repo.create_participant(
        SqliteRuntimeConnection(conn),
            participant_id="del-tok",
            display_name="Token Delete",
        )
        conn.close()

        subprocess.run(
            [
                venv_python, "-m", "scripts.delete_participant",
                "del-tok",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        conn = get_connection(initialized_db)
        found = repo.get_active_participant_by_token(
            conn, prov.one_time_token
        )
        conn.close()
        assert found is None


class TestInspectRecords:
    def test_inspect_text_output(self, initialized_db, venv_python):
        conn = get_connection(initialized_db)
        repo.create_participant(
        SqliteRuntimeConnection(conn),
            participant_id="ins-p1",
            display_name="Inspect Me",
        )
        conn.close()

        result = subprocess.run(
            [
                venv_python, "-m", "scripts.inspect_records",
                "ins-p1",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "ins-p1" in result.stdout
        assert "Inspect Me" in result.stdout

    def test_inspect_json_output(self, initialized_db, venv_python):
        conn = get_connection(initialized_db)
        repo.create_participant(
        SqliteRuntimeConnection(conn),
            participant_id="ins-p2",
            display_name="JSON Inspect",
        )
        conn.close()

        result = subprocess.run(
            [
                venv_python, "-m", "scripts.inspect_records",
                "ins-p2",
                "--json",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["participant"]["id"] == "ins-p2"
        assert data["participant"]["display_name"] == "JSON Inspect"

    def test_inspect_nonexistent_fails(self, initialized_db, venv_python):
        result = subprocess.run(
            [
                venv_python, "-m", "scripts.inspect_records",
                "no-such",
                "--database", initialized_db,
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 1
