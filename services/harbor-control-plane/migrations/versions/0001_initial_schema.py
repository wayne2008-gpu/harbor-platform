"""initial control-plane schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("job_config_json", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("runner_id", sa.String(length=128), nullable=True),
        sa.Column("lease_id", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_state_created_at", "jobs", ["state", "created_at"])
    op.create_index("ix_jobs_runner_id_state", "jobs", ["runner_id", "state"])
    op.create_index("ix_jobs_lease_expires_at", "jobs", ["lease_expires_at"])
    op.create_index("ix_jobs_updated_at", "jobs", ["updated_at"])

    op.create_table(
        "trials",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("task_name", sa.String(length=255), nullable=True),
        sa.Column("agent_name", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("reward", sa.String(length=64), nullable=True),
        sa.Column("exception_type", sa.String(length=128), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_trials_job_id_state", "trials", ["job_id", "state"])
    op.create_index("ix_trials_job_id_task_name", "trials", ["job_id", "task_name"])

    op.create_table(
        "runners",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=True),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("jobs_dir", sa.String(length=1024), nullable=True),
        sa.Column("max_running_jobs", sa.Integer(), nullable=True),
        sa.Column("running_jobs", sa.Integer(), nullable=False),
        sa.Column("internal_url", sa.String(length=1024), nullable=True),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runners_state_heartbeat", "runners", ["state", "last_heartbeat_at"])

    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("runner_id", sa.String(length=128), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_id_created_at", "job_events", ["job_id", "created_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("trial_id", sa.String(length=128), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("storage_type", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=2048), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])
    op.create_index("ix_artifacts_trial_id", "artifacts", ["trial_id"])


def downgrade() -> None:
    for table in ["artifacts", "job_events", "runners", "trials", "jobs"]:
        op.drop_table(table)
