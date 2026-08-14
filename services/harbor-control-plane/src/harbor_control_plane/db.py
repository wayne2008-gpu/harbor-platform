from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

jobs_table = Table(
    "jobs",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("state", String(32), nullable=False, index=True),
    Column("job_config_json", JSON, nullable=False),
    Column("provider", String(32), nullable=True, index=True),
    Column("runner_id", String(128), nullable=True, index=True),
    Column("lease_id", String(64), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True, index=True),
    Column("cancel_requested_at", DateTime(timezone=True), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, index=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_type", String(128), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("result_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

trials_table = Table(
    "trials",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("job_id", String(32), nullable=False, index=True),
    Column("task_name", String(255), nullable=True, index=True),
    Column("agent_name", String(128), nullable=True),
    Column("model_name", String(255), nullable=True),
    Column("state", String(32), nullable=False, index=True),
    Column("attempt", Integer, nullable=True),
    Column("reward", String(64), nullable=True),
    Column("exception_type", String(128), nullable=True),
    Column("result_json", JSON, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
)

runners_table = Table(
    "runners",
    metadata,
    Column("id", String(128), primary_key=True),
    Column("state", String(32), nullable=False, index=True),
    Column("hostname", String(255), nullable=True),
    Column("version", String(64), nullable=True),
    Column("jobs_dir", String(1024), nullable=True),
    Column("max_running_jobs", Integer, nullable=True),
    Column("running_jobs", Integer, nullable=False, default=0),
    Column("internal_url", String(1024), nullable=True),
    Column("capabilities_json", JSON, nullable=False),
    Column("last_heartbeat_at", DateTime(timezone=True), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

job_events_table = Table(
    "job_events",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("job_id", String(32), nullable=False, index=True),
    Column("runner_id", String(128), nullable=True),
    Column("event_type", String(64), nullable=False),
    Column("payload_json", JSON, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)

artifacts_table = Table(
    "artifacts",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("job_id", String(32), nullable=False, index=True),
    Column("trial_id", String(128), nullable=True, index=True),
    Column("kind", String(64), nullable=False),
    Column("storage_type", String(32), nullable=False),
    Column("storage_key", String(2048), nullable=False),
    Column("size_bytes", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def create_schema(engine: Engine) -> None:
    metadata.create_all(engine)
