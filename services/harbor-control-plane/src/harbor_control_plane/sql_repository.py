from datetime import UTC, datetime
from typing import Any

from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactResponse,
    ArtifactState,
    InputDataset,
    InputState,
    JobSnapshotRequest,
    JobState,
    MaterializedInputDataset,
    RunnerHeartbeatRequest,
    RunnerState,
    TrialState,
    TrialStatusResponse,
)
from sqlalchemy import Engine, and_, delete, insert, select, update

from harbor_control_plane.db import (
    artifacts_table,
    job_events_table,
    jobs_table,
    runners_table,
    trials_table,
)
from harbor_control_plane.repository import (
    JobNotFoundError,
    JobRecord,
    RunnerRecord,
    _trial_statuses_from_result_json,
)


class SqlJobRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_job(
        self,
        *,
        job_id: str,
        job_config: dict[str, Any],
        input_datasets: list[InputDataset] | None = None,
        provider: str | None = None,
    ) -> JobRecord:
        now = _utcnow()
        input_datasets = input_datasets or []
        with self.engine.begin() as connection:
            connection.execute(
                insert(jobs_table).values(
                    id=job_id,
                    state=JobState.QUEUED.value,
                    input_state=InputState.PENDING.value,
                    artifact_state=ArtifactState.PENDING.value,
                    job_config_json=job_config,
                    input_datasets_json=[
                        dataset.model_dump(mode="json") for dataset in input_datasets
                    ],
                    materialized_inputs_json=[],
                    provider=provider,
                    updated_at=now,
                    created_at=now,
                )
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="queued",
                payload={"provider": provider},
                created_at=now,
            )
        return self.get_job(job_id)

    def mark_dispatch_failed(self, job_id: str, *, error_message: str) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table)
                .where(jobs_table.c.id == job_id)
                .values(
                    state=JobState.FAILED.value,
                    error_type="dispatch_failed",
                    error_message=error_message,
                    updated_at=now,
                    finished_at=now,
                )
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="dispatch_failed",
                payload={
                    "previous_state": record.state.value,
                    "error_message": error_message,
                },
                created_at=now,
            )
        return self.get_job(job_id)

    def list_queued_job_ids(self, *, limit: int) -> list[str]:
        self.requeue_expired_leases()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(jobs_table.c.id)
                .where(
                    jobs_table.c.state == JobState.QUEUED.value,
                    jobs_table.c.cancel_requested_at.is_(None),
                )
                .order_by(jobs_table.c.created_at)
                .limit(limit)
            ).all()
        return [row[0] for row in rows]

    def requeue_expired_leases(self, *, now: datetime | None = None) -> list[str]:
        cutoff = now or _utcnow()
        with self.engine.begin() as connection:
            expired_rows = (
                connection.execute(
                    select(
                        jobs_table.c.id,
                        jobs_table.c.runner_id,
                        jobs_table.c.lease_id,
                    ).where(
                        jobs_table.c.state == JobState.LEASED.value,
                        jobs_table.c.cancel_requested_at.is_(None),
                        jobs_table.c.lease_expires_at.is_not(None),
                        jobs_table.c.lease_expires_at <= cutoff,
                    )
                )
                .mappings()
                .all()
            )
            if not expired_rows:
                return []
            job_ids = [row["id"] for row in expired_rows]
            connection.execute(
                update(jobs_table)
                .where(jobs_table.c.id.in_(job_ids))
                .values(
                    state=JobState.QUEUED.value,
                    runner_id=None,
                    lease_id=None,
                    lease_expires_at=None,
                    updated_at=cutoff,
                )
            )
            for row in expired_rows:
                self._insert_event(
                    connection,
                    job_id=row["id"],
                    runner_id=row["runner_id"],
                    event_type="lease_expired",
                    payload={"lease_id": row["lease_id"]},
                    created_at=cutoff,
                )
        return job_ids

    def get_job(self, job_id: str) -> JobRecord:
        with self.engine.begin() as connection:
            row = (
                connection.execute(select(jobs_table).where(jobs_table.c.id == job_id))
                .mappings()
                .first()
            )
        if row is None:
            raise JobNotFoundError(job_id)
        return _job_record_from_row(row)

    def list_trials(self, job_id: str) -> list[TrialStatusResponse]:
        self.get_job(job_id)
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(trials_table).where(trials_table.c.job_id == job_id)
                )
                .mappings()
                .all()
            )
        return [_trial_response_from_row(row) for row in rows]

    def request_cancel(self, job_id: str) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        next_state = (
            JobState.CANCELLED if record.state == JobState.QUEUED else record.state
        )
        finished_at = now if next_state == JobState.CANCELLED else record.finished_at
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table)
                .where(jobs_table.c.id == job_id)
                .values(
                    state=next_state.value,
                    cancel_requested_at=now,
                    updated_at=now,
                    finished_at=finished_at,
                )
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="cancel_requested",
                payload={"previous_state": record.state.value},
                created_at=now,
            )
        return self.get_job(job_id)

    def acquire_lease(
        self,
        *,
        job_id: str,
        runner_id: str,
        lease_id: str,
        lease_expires_at: datetime,
    ) -> bool:
        now = _utcnow()
        self.requeue_expired_leases(now=now)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(jobs_table)
                .where(
                    and_(
                        jobs_table.c.id == job_id,
                        jobs_table.c.state == JobState.QUEUED.value,
                        jobs_table.c.cancel_requested_at.is_(None),
                    )
                )
                .values(
                    state=JobState.LEASED.value,
                    runner_id=runner_id,
                    lease_id=lease_id,
                    lease_expires_at=lease_expires_at,
                    updated_at=now,
                )
            )
            acquired = result.rowcount == 1
            if acquired:
                self._insert_event(
                    connection,
                    job_id=job_id,
                    runner_id=runner_id,
                    event_type="leased",
                    payload={"lease_id": lease_id},
                    created_at=now,
                )
        return acquired

    def apply_snapshot(self, job_id: str, snapshot: JobSnapshotRequest) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        trial_rows = _trial_statuses_from_result_json(
            job_id, snapshot.result_json, updated_at=now
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table)
                .where(jobs_table.c.id == job_id)
                .values(
                    state=snapshot.state.value,
                    runner_id=snapshot.runner_id,
                    started_at=snapshot.started_at or record.started_at,
                    finished_at=snapshot.finished_at or record.finished_at,
                    error_type=snapshot.error_type,
                    error_message=snapshot.error_message,
                    result_json=snapshot.result_json,
                    updated_at=now,
                )
            )
            if trial_rows is not None:
                connection.execute(
                    delete(trials_table).where(trials_table.c.job_id == job_id)
                )
                if trial_rows:
                    connection.execute(
                        insert(trials_table),
                        [_trial_insert_values(trial) for trial in trial_rows],
                    )
            self._insert_event(
                connection,
                job_id=job_id,
                runner_id=snapshot.runner_id,
                event_type="snapshot",
                payload={"state": snapshot.state.value},
                created_at=now,
            )
        return self.get_job(job_id)

    def heartbeat_runner(self, request: RunnerHeartbeatRequest) -> RunnerRecord:
        now = _utcnow()
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(runners_table.c.id).where(
                    runners_table.c.id == request.runner_id
                )
            ).first()
            values = {
                "state": request.state.value,
                "running_jobs": request.running_jobs,
                "capabilities_json": request.capabilities,
                "last_heartbeat_at": now,
                "updated_at": now,
            }
            if existing is None:
                connection.execute(
                    insert(runners_table).values(
                        id=request.runner_id,
                        hostname=None,
                        version=None,
                        jobs_dir=None,
                        max_running_jobs=None,
                        internal_url=None,
                        created_at=now,
                        **values,
                    )
                )
            else:
                connection.execute(
                    update(runners_table)
                    .where(runners_table.c.id == request.runner_id)
                    .values(**values)
                )
        return self._get_runner(request.runner_id)

    def list_runners(self) -> list[RunnerRecord]:
        with self.engine.begin() as connection:
            rows = connection.execute(select(runners_table)).mappings().all()
        return [_runner_record_from_row(row) for row in rows]

    def mark_stale_runners_offline(self, *, stale_before: datetime) -> list[str]:
        now = _utcnow()
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(runners_table.c.id).where(
                    runners_table.c.state != RunnerState.OFFLINE.value,
                    runners_table.c.last_heartbeat_at <= stale_before,
                )
            ).all()
            runner_ids = [row[0] for row in rows]
            if not runner_ids:
                return []
            connection.execute(
                update(runners_table)
                .where(runners_table.c.id.in_(runner_ids))
                .values(state=RunnerState.OFFLINE.value, updated_at=now)
            )
        return runner_ids

    def _get_runner(self, runner_id: str) -> RunnerRecord:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(runners_table).where(runners_table.c.id == runner_id)
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ValueError(f"Runner not found: {runner_id}")
        return _runner_record_from_row(row)

    def record_artifact(
        self, job_id: str, request: ArtifactCreateRequest
    ) -> ArtifactResponse:
        self.get_job(job_id)
        now = _utcnow()
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(artifacts_table).values(
                    job_id=job_id,
                    trial_id=request.trial_id,
                    kind=request.kind,
                    storage_type=request.storage_type,
                    storage_key=request.storage_key,
                    relative_path=request.relative_path,
                    checksum_sha256=request.checksum_sha256,
                    etag=request.etag,
                    content_type=request.content_type,
                    size_bytes=request.size_bytes,
                    metadata_json=request.metadata,
                    uploaded_at=request.uploaded_at,
                    created_at=now,
                )
            )
            artifact_id = int(result.inserted_primary_key[0])
        return ArtifactResponse(
            id=artifact_id,
            job_id=job_id,
            trial_id=request.trial_id,
            kind=request.kind,
            storage_type=request.storage_type,
            storage_key=request.storage_key,
            relative_path=request.relative_path,
            checksum_sha256=request.checksum_sha256,
            etag=request.etag,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            uploaded_at=request.uploaded_at,
            metadata=request.metadata,
            created_at=now,
        )

    def update_artifact_state(
        self,
        job_id: str,
        *,
        artifact_state: ArtifactState,
        error_message: str | None = None,
    ) -> JobRecord:
        self.get_job(job_id)
        now = _utcnow()
        values: dict[str, Any] = {
            "artifact_state": artifact_state.value,
            "updated_at": now,
        }
        if error_message is not None:
            values["error_message"] = error_message
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table).where(jobs_table.c.id == job_id).values(**values)
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="artifact_state",
                payload={
                    "artifact_state": artifact_state.value,
                    "error_message": error_message,
                },
                created_at=now,
            )
        return self.get_job(job_id)

    def update_input_state(
        self,
        job_id: str,
        *,
        input_state: InputState,
        materialized_inputs: list[MaterializedInputDataset] | None = None,
        error_message: str | None = None,
    ) -> JobRecord:
        self.get_job(job_id)
        now = _utcnow()
        values: dict[str, Any] = {
            "input_state": input_state.value,
            "updated_at": now,
        }
        if materialized_inputs is not None:
            values["materialized_inputs_json"] = [
                item.model_dump(mode="json") for item in materialized_inputs
            ]
        if error_message is not None:
            values["error_message"] = error_message
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table).where(jobs_table.c.id == job_id).values(**values)
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="input_state",
                payload={
                    "input_state": input_state.value,
                    "error_message": error_message,
                },
                created_at=now,
            )
        return self.get_job(job_id)

    def mark_input_materialization_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        materialized_inputs: list[MaterializedInputDataset] | None = None,
    ) -> JobRecord:
        self.get_job(job_id)
        now = _utcnow()
        values: dict[str, Any] = {
            "state": JobState.FAILED.value,
            "input_state": InputState.FAILED.value,
            "error_type": "input_materialization_failed",
            "error_message": error_message,
            "updated_at": now,
            "finished_at": now,
        }
        if materialized_inputs is not None:
            values["materialized_inputs_json"] = [
                item.model_dump(mode="json") for item in materialized_inputs
            ]
        with self.engine.begin() as connection:
            connection.execute(
                update(jobs_table).where(jobs_table.c.id == job_id).values(**values)
            )
            self._insert_event(
                connection,
                job_id=job_id,
                event_type="input_materialization_failed",
                payload={"error_message": error_message},
                created_at=now,
            )
        return self.get_job(job_id)

    def list_artifacts(self, job_id: str) -> list[ArtifactResponse]:
        self.get_job(job_id)
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(artifacts_table).where(artifacts_table.c.job_id == job_id)
                )
                .mappings()
                .all()
            )
        return [_artifact_response_from_row(row) for row in rows]

    def get_artifact(self, job_id: str, artifact_id: int) -> ArtifactResponse:
        self.get_job(job_id)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(artifacts_table).where(
                        artifacts_table.c.job_id == job_id,
                        artifacts_table.c.id == artifact_id,
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ValueError(str(artifact_id))
        return _artifact_response_from_row(row)

    def _insert_event(
        self,
        connection,
        *,
        job_id: str,
        event_type: str,
        created_at: datetime,
        runner_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            insert(job_events_table).values(
                job_id=job_id,
                runner_id=runner_id,
                event_type=event_type,
                payload_json=payload,
                created_at=created_at,
            )
        )


def _job_record_from_row(row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        state=JobState(row["state"]),
        input_state=InputState(row["input_state"]),
        artifact_state=ArtifactState(row["artifact_state"]),
        job_config=row["job_config_json"],
        input_datasets=[
            InputDataset.model_validate(item)
            for item in (row["input_datasets_json"] or [])
        ],
        materialized_inputs=[
            MaterializedInputDataset.model_validate(item)
            for item in (row["materialized_inputs_json"] or [])
        ],
        provider=row["provider"],
        runner_id=row["runner_id"],
        lease_id=row["lease_id"],
        lease_expires_at=row["lease_expires_at"],
        cancel_requested_at=row["cancel_requested_at"],
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
        error_type=row["error_type"],
        error_message=row["error_message"],
        result_json=row["result_json"],
    )


def _runner_record_from_row(row) -> RunnerRecord:
    return RunnerRecord(
        id=row["id"],
        state=RunnerState(row["state"]),
        running_jobs=row["running_jobs"],
        capabilities=row["capabilities_json"],
        last_heartbeat_at=row["last_heartbeat_at"],
    )


def _artifact_response_from_row(row) -> ArtifactResponse:
    return ArtifactResponse(
        id=row["id"],
        job_id=row["job_id"],
        trial_id=row["trial_id"],
        kind=row["kind"],
        storage_type=row["storage_type"],
        storage_key=row["storage_key"],
        relative_path=row["relative_path"],
        checksum_sha256=row["checksum_sha256"],
        etag=row["etag"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        uploaded_at=row["uploaded_at"],
        metadata=row["metadata_json"],
        created_at=row["created_at"],
    )


def _trial_response_from_row(row) -> TrialStatusResponse:
    reward = row["reward"]
    return TrialStatusResponse(
        id=row["id"],
        job_id=row["job_id"],
        state=TrialState(row["state"]),
        task_name=row["task_name"],
        agent_name=row["agent_name"],
        model_name=row["model_name"],
        reward=float(reward) if reward is not None else None,
        exception_type=row["exception_type"],
        result_json=row["result_json"],
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        finished_at=row["finished_at"],
    )


def _trial_insert_values(trial: TrialStatusResponse) -> dict[str, Any]:
    return {
        "id": trial.id,
        "job_id": trial.job_id,
        "task_name": trial.task_name,
        "agent_name": trial.agent_name,
        "model_name": trial.model_name,
        "state": trial.state.value,
        "attempt": None,
        "reward": str(trial.reward) if trial.reward is not None else None,
        "exception_type": trial.exception_type,
        "result_json": trial.result_json,
        "started_at": trial.started_at,
        "updated_at": trial.updated_at,
        "finished_at": trial.finished_at,
    }


def _utcnow() -> datetime:
    return datetime.now(UTC)
