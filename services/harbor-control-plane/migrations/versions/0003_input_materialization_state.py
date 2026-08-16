"""add input materialization state

Revision ID: 0003_input_materialization_state
Revises: 0002_artifact_storage_metadata
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_input_materialization_state"
down_revision = "0002_artifact_storage_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "input_state",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
    )
    op.alter_column(
        "jobs",
        "input_state",
        existing_type=sa.String(length=32),
        server_default=None,
    )

    op.add_column(
        "jobs",
        sa.Column("input_datasets_json", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE jobs SET input_datasets_json = '[]' WHERE input_datasets_json IS NULL"
    )
    op.alter_column(
        "jobs",
        "input_datasets_json",
        existing_type=sa.JSON(),
        nullable=False,
    )

    op.add_column(
        "jobs",
        sa.Column("materialized_inputs_json", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE jobs SET materialized_inputs_json = '[]' "
        "WHERE materialized_inputs_json IS NULL"
    )
    op.alter_column(
        "jobs",
        "materialized_inputs_json",
        existing_type=sa.JSON(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("jobs", "materialized_inputs_json")
    op.drop_column("jobs", "input_datasets_json")
    op.drop_column("jobs", "input_state")
