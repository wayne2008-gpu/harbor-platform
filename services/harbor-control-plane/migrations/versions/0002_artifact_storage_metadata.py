"""add artifact storage metadata

Revision ID: 0002_artifact_storage_metadata
Revises: 0001_initial_schema
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_artifact_storage_metadata"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "artifact_state",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.alter_column(
        "jobs",
        "artifact_state",
        existing_type=sa.String(length=32),
        server_default=None,
    )

    op.add_column("artifacts", sa.Column("relative_path", sa.String(length=2048)))
    op.add_column("artifacts", sa.Column("checksum_sha256", sa.String(length=64)))
    op.add_column("artifacts", sa.Column("etag", sa.String(length=255)))
    op.add_column("artifacts", sa.Column("content_type", sa.String(length=255)))
    op.add_column(
        "artifacts",
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )
    op.execute("UPDATE artifacts SET metadata_json = '{}' WHERE metadata_json IS NULL")
    op.alter_column(
        "artifacts",
        "metadata_json",
        existing_type=sa.JSON(),
        nullable=False,
    )
    op.add_column("artifacts", sa.Column("uploaded_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("artifacts", "uploaded_at")
    op.drop_column("artifacts", "metadata_json")
    op.drop_column("artifacts", "content_type")
    op.drop_column("artifacts", "etag")
    op.drop_column("artifacts", "checksum_sha256")
    op.drop_column("artifacts", "relative_path")
    op.drop_column("jobs", "artifact_state")
