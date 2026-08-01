"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-01
"""
from alembic import op
from sqlalchemy import inspect

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema is driven by the ORM metadata (app.models.Base.metadata) so the
    # migration always matches the models. Portable to SQLite and PostgreSQL.
    from app import models  # noqa: F401

    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("communities"):
        models.Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app import models  # noqa: F401

    bind = op.get_bind()
    # drop in reverse dependency order is handled by metadata.drop_all
    models.Base.metadata.drop_all(bind=bind)
