"""add query cancel claim retry fields

Revision ID: 0004_query_cancel_claim_retry
Revises: 0003_input_materialization_state
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_query_cancel_claim_retry"
down_revision = "0003_input_materialization_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("requirements_json", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE jobs SET requirements_json = '{}' WHERE requirements_json IS NULL"
    )
    op.alter_column(
        "jobs",
        "requirements_json",
        existing_type=sa.JSON(),
        nullable=False,
    )
    op.add_column("jobs", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("cancel_mode", sa.String(length=32), nullable=True))
    op.add_column(
        "jobs", sa.Column("cancel_grace_period_sec", sa.Float(), nullable=True)
    )
    op.add_column(
        "jobs",
        sa.Column("cancel_deadline_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "jobs", sa.Column("cancelled_by", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "jobs", sa.Column("parent_job_id", sa.String(length=32), nullable=True)
    )
    op.add_column("jobs", sa.Column("root_job_id", sa.String(length=32), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("jobs", "attempt", existing_type=sa.Integer(), server_default=None)
    op.add_column("jobs", sa.Column("retry_reason", sa.Text(), nullable=True))
    op.execute("UPDATE jobs SET root_job_id = id WHERE root_job_id IS NULL")

    op.create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"])
    op.create_index("ix_jobs_root_job_id", "jobs", ["root_job_id"])
    op.create_index("ix_jobs_state_created_at", "jobs", ["state", "created_at"])
    op.create_index("ix_jobs_updated_at_id", "jobs", ["updated_at", "id"])
    op.create_index("ix_jobs_provider_created_at", "jobs", ["provider", "created_at"])
    op.create_index("ix_trials_job_id_state", "trials", ["job_id", "state"])
    op.create_index("ix_trials_job_id_task_name", "trials", ["job_id", "task_name"])
    op.create_index("ix_trials_updated_at_id", "trials", ["updated_at", "id"])
    op.create_index("ix_artifacts_job_id_kind", "artifacts", ["job_id", "kind"])
    op.create_index(
        "ix_artifacts_job_id_trial_id_kind",
        "artifacts",
        ["job_id", "trial_id", "kind"],
    )
    op.create_index("ix_artifacts_created_at_id", "artifacts", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_created_at_id", table_name="artifacts")
    op.drop_index("ix_artifacts_job_id_trial_id_kind", table_name="artifacts")
    op.drop_index("ix_artifacts_job_id_kind", table_name="artifacts")
    op.drop_index("ix_trials_updated_at_id", table_name="trials")
    op.drop_index("ix_trials_job_id_task_name", table_name="trials")
    op.drop_index("ix_trials_job_id_state", table_name="trials")
    op.drop_index("ix_jobs_provider_created_at", table_name="jobs")
    op.drop_index("ix_jobs_updated_at_id", table_name="jobs")
    op.drop_index("ix_jobs_state_created_at", table_name="jobs")
    op.drop_index("ix_jobs_root_job_id", table_name="jobs")
    op.drop_index("ix_jobs_parent_job_id", table_name="jobs")
    op.drop_column("jobs", "retry_reason")
    op.drop_column("jobs", "attempt")
    op.drop_column("jobs", "root_job_id")
    op.drop_column("jobs", "parent_job_id")
    op.drop_column("jobs", "cancelled_by")
    op.drop_column("jobs", "cancel_deadline_at")
    op.drop_column("jobs", "cancel_grace_period_sec")
    op.drop_column("jobs", "cancel_mode")
    op.drop_column("jobs", "cancel_reason")
    op.drop_column("jobs", "requirements_json")
