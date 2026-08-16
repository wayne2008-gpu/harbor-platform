import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactPageResponse,
    ArtifactQueryRequest,
    ArtifactResponse,
    ArtifactRetryRequest,
    ArtifactState,
    InputDataset,
    InputState,
    JobBatchGetRequest,
    JobCancelRequest,
    JobClaimedLease,
    JobClaimRequest,
    JobClaimResponse,
    JobControlResponse,
    JobPageResponse,
    JobQueryRequest,
    JobRetryRequest,
    JobSnapshotRequest,
    JobState,
    JobStatusResponse,
    MaterializedInputDataset,
    RunnerHeartbeatRequest,
    RunnerState,
    RunnerStatusResponse,
    TrialPageResponse,
    TrialQueryRequest,
    TrialState,
    TrialStatusResponse,
)


class JobNotFoundError(ValueError):
    pass


@dataclass
class JobRecord:
    id: str
    state: JobState
    input_state: InputState
    artifact_state: ArtifactState
    job_config: dict[str, Any]
    input_datasets: list[InputDataset]
    materialized_inputs: list[MaterializedInputDataset]
    requirements: dict[str, Any]
    provider: str | None
    created_at: datetime
    updated_at: datetime
    runner_id: str | None = None
    lease_id: str | None = None
    lease_expires_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    cancel_reason: str | None = None
    cancel_mode: str | None = None
    cancel_grace_period_sec: float | None = None
    cancel_deadline_at: datetime | None = None
    cancelled_by: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None
    result_json: dict[str, Any] | None = None
    parent_job_id: str | None = None
    root_job_id: str | None = None
    attempt: int = 1
    retry_reason: str | None = None

    def to_response(self) -> JobStatusResponse:
        return JobStatusResponse(
            id=self.id,
            state=self.state,
            input_state=self.input_state,
            artifact_state=self.artifact_state,
            job_config=self.job_config,
            input_datasets=self.input_datasets,
            materialized_inputs=self.materialized_inputs,
            requirements=self.requirements,
            provider=self.provider,
            runner_id=self.runner_id,
            cancel_requested_at=self.cancel_requested_at,
            cancel_reason=self.cancel_reason,
            cancel_mode=self.cancel_mode,
            cancel_grace_period_sec=self.cancel_grace_period_sec,
            cancel_deadline_at=self.cancel_deadline_at,
            cancelled_by=self.cancelled_by,
            started_at=self.started_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
            finished_at=self.finished_at,
            error_type=self.error_type,
            error_message=self.error_message,
            result_json=self.result_json,
            parent_job_id=self.parent_job_id,
            root_job_id=self.root_job_id,
            attempt=self.attempt,
            retry_reason=self.retry_reason,
        )


@dataclass
class RunnerRecord:
    id: str
    state: RunnerState
    running_jobs: int
    capabilities: dict[str, Any]
    last_heartbeat_at: datetime

    def to_response(self) -> RunnerStatusResponse:
        return RunnerStatusResponse(
            id=self.id,
            state=self.state,
            running_jobs=self.running_jobs,
            capabilities=self.capabilities,
            last_heartbeat_at=self.last_heartbeat_at,
        )


class InMemoryJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, JobRecord] = {}
        self.trials: dict[str, list[TrialStatusResponse]] = {}
        self.runners: dict[str, RunnerRecord] = {}
        self.artifacts: dict[str, list[ArtifactResponse]] = {}
        self._next_artifact_id = 1

    def create_job(
        self,
        *,
        job_id: str,
        job_config: dict[str, Any],
        input_datasets: list[InputDataset] | None = None,
        requirements: dict[str, Any] | None = None,
        provider: str | None = None,
        parent_job_id: str | None = None,
        root_job_id: str | None = None,
        attempt: int = 1,
        retry_reason: str | None = None,
    ) -> JobRecord:
        now = _utcnow()
        input_datasets = input_datasets or []
        record = JobRecord(
            id=job_id,
            state=JobState.QUEUED,
            input_state=InputState.PENDING,
            artifact_state=ArtifactState.PENDING,
            job_config=job_config,
            input_datasets=input_datasets,
            materialized_inputs=[],
            requirements=requirements or {},
            provider=provider,
            created_at=now,
            updated_at=now,
            parent_job_id=parent_job_id,
            root_job_id=root_job_id or job_id,
            attempt=attempt,
            retry_reason=retry_reason,
        )
        self.jobs[job_id] = record
        return record

    def mark_dispatch_failed(self, job_id: str, *, error_message: str) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        record.state = JobState.FAILED
        record.error_type = "dispatch_failed"
        record.error_message = error_message
        record.updated_at = now
        record.finished_at = now
        return record

    def list_queued_job_ids(self, *, limit: int) -> list[str]:
        self.requeue_expired_leases()
        return [
            job.id
            for job in self.jobs.values()
            if job.state == JobState.QUEUED and job.cancel_requested_at is None
        ][:limit]

    def requeue_expired_leases(self, *, now: datetime | None = None) -> list[str]:
        cutoff = now or _utcnow()
        requeued: list[str] = []
        for record in self.jobs.values():
            if (
                record.state != JobState.LEASED
                or record.cancel_requested_at is not None
                or record.lease_expires_at is None
                or record.lease_expires_at > cutoff
            ):
                continue
            record.state = JobState.QUEUED
            record.runner_id = None
            record.lease_id = None
            record.lease_expires_at = None
            record.updated_at = cutoff
            requeued.append(record.id)
        return requeued

    def get_job(self, job_id: str) -> JobRecord:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError(job_id) from exc

    def list_trials(self, job_id: str) -> list[TrialStatusResponse]:
        self.get_job(job_id)
        return list(self.trials.get(job_id, []))

    def batch_get_jobs(self, request: JobBatchGetRequest) -> list[JobStatusResponse]:
        return [
            self.jobs[job_id].to_response()
            for job_id in request.ids
            if job_id in self.jobs
        ]

    def query_jobs(self, request: JobQueryRequest) -> JobPageResponse:
        items = [
            record
            for record in self.jobs.values()
            if _job_matches_query(record, request)
        ]
        page, next_cursor = _page_by_key(
            sorted(items, key=lambda item: (item.created_at, item.id)),
            limit=request.limit,
            cursor=request.cursor,
            key=lambda item: (item.created_at, item.id),
        )
        return JobPageResponse(
            items=[item.to_response() for item in page],
            next_cursor=next_cursor,
            limit=request.limit,
        )

    def query_trials(self, request: TrialQueryRequest) -> TrialPageResponse:
        items = [
            trial
            for trials in self.trials.values()
            for trial in trials
            if _trial_matches_query(trial, request)
        ]
        page, next_cursor = _page_by_key(
            sorted(items, key=lambda item: (item.updated_at, item.id)),
            limit=request.limit,
            cursor=request.cursor,
            key=lambda item: (item.updated_at, item.id),
        )
        return TrialPageResponse(
            items=page, next_cursor=next_cursor, limit=request.limit
        )

    def query_artifacts(self, request: ArtifactQueryRequest) -> ArtifactPageResponse:
        items = [
            artifact
            for artifacts in self.artifacts.values()
            for artifact in artifacts
            if _artifact_matches_query(artifact, request)
        ]
        page, next_cursor = _page_by_key(
            sorted(items, key=lambda item: (item.created_at, str(item.id))),
            limit=request.limit,
            cursor=request.cursor,
            key=lambda item: (item.created_at, str(item.id)),
        )
        return ArtifactPageResponse(
            items=page,
            next_cursor=next_cursor,
            limit=request.limit,
        )

    def request_cancel(
        self,
        job_id: str,
        request: JobCancelRequest | None = None,
    ) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        request = request or JobCancelRequest()
        if record.state in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMED_OUT,
        }:
            return record
        record.cancel_requested_at = now
        record.cancel_reason = request.reason
        record.cancel_mode = request.mode
        record.cancel_grace_period_sec = request.grace_period_sec
        record.cancel_deadline_at = (
            now + timedelta(seconds=request.grace_period_sec)
            if request.grace_period_sec is not None
            else None
        )
        record.cancelled_by = request.cancelled_by
        record.updated_at = now
        if record.state == JobState.QUEUED:
            record.state = JobState.CANCELLED
            record.finished_at = now
        elif record.state in {JobState.LEASED, JobState.RUNNING}:
            record.state = JobState.CANCELLING
        return record

    def get_job_control(self, job_id: str) -> JobControlResponse:
        record = self.get_job(job_id)
        return JobControlResponse(
            job_id=record.id,
            state=record.state,
            cancel_requested=record.cancel_requested_at is not None,
            cancel_mode=record.cancel_mode,
            cancel_reason=record.cancel_reason,
            cancel_grace_period_sec=record.cancel_grace_period_sec,
            cancel_deadline_at=record.cancel_deadline_at,
        )

    def claim_jobs(self, request: JobClaimRequest) -> JobClaimResponse:
        now = _utcnow()
        self.requeue_expired_leases(now=now)
        runner = self.runners.get(request.runner_id)
        capabilities = request.capabilities or (runner.capabilities if runner else {})
        claimed: list[JobClaimedLease] = []
        for record in sorted(self.jobs.values(), key=lambda item: item.created_at):
            if len(claimed) >= request.max_jobs:
                break
            if (
                record.state != JobState.QUEUED
                or record.cancel_requested_at is not None
            ):
                continue
            if not _matches_requirements(record.requirements, capabilities):
                continue
            lease_id = uuid4().hex
            lease_expires_at = now + timedelta(seconds=request.lease_duration_sec)
            record.state = JobState.LEASED
            record.runner_id = request.runner_id
            record.lease_id = lease_id
            record.lease_expires_at = lease_expires_at
            record.updated_at = now
            claimed.append(
                JobClaimedLease(
                    job_id=record.id,
                    lease_id=lease_id,
                    lease_expires_at=lease_expires_at,
                    action="run",
                    job=record.to_response(),
                )
            )
        for record in sorted(self.jobs.values(), key=lambda item: item.updated_at):
            if len(claimed) >= request.max_jobs:
                break
            if not _is_artifact_retry_claimable(record, request.runner_id):
                continue
            lease_id = uuid4().hex
            lease_expires_at = now + timedelta(seconds=request.lease_duration_sec)
            record.artifact_state = ArtifactState.UPLOADING
            record.lease_id = lease_id
            record.lease_expires_at = lease_expires_at
            record.updated_at = now
            claimed.append(
                JobClaimedLease(
                    job_id=record.id,
                    lease_id=lease_id,
                    lease_expires_at=lease_expires_at,
                    action="artifact-retry",
                    job=record.to_response(),
                )
            )
        return JobClaimResponse(claimed=claimed)

    def retry_job(
        self,
        job_id: str,
        *,
        new_job_id: str,
        request: JobRetryRequest,
    ) -> JobRecord:
        original = self.get_job(job_id)
        return self.create_job(
            job_id=new_job_id,
            job_config=original.job_config,
            input_datasets=original.input_datasets,
            requirements=original.requirements,
            provider=original.provider,
            parent_job_id=original.id,
            root_job_id=original.root_job_id or original.id,
            attempt=original.attempt + 1,
            retry_reason=request.reason,
        )

    def request_artifact_retry(
        self,
        job_id: str,
        request: ArtifactRetryRequest,
    ) -> JobRecord:
        record = self.get_job(job_id)
        record.artifact_state = ArtifactState.PENDING
        record.error_message = request.reason
        record.updated_at = _utcnow()
        return record

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
        record = self.get_job(job_id)
        if record.state != JobState.QUEUED or record.cancel_requested_at is not None:
            return False
        record.state = JobState.LEASED
        record.runner_id = runner_id
        record.lease_id = lease_id
        record.lease_expires_at = lease_expires_at
        record.updated_at = now
        return True

    def apply_snapshot(self, job_id: str, snapshot: JobSnapshotRequest) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        trial_rows = _trial_statuses_from_result_json(
            job_id, snapshot.result_json, updated_at=now
        )
        record.state = (
            JobState.CANCELLING
            if record.state == JobState.CANCELLING
            and snapshot.state == JobState.RUNNING
            else snapshot.state
        )
        record.runner_id = snapshot.runner_id
        record.started_at = snapshot.started_at or record.started_at
        record.finished_at = snapshot.finished_at or record.finished_at
        record.error_type = snapshot.error_type
        record.error_message = snapshot.error_message
        record.result_json = snapshot.result_json
        record.updated_at = now
        if trial_rows is not None:
            self.trials[job_id] = trial_rows
        return record

    def heartbeat_runner(self, request: RunnerHeartbeatRequest) -> RunnerRecord:
        now = _utcnow()
        record = RunnerRecord(
            id=request.runner_id,
            state=request.state,
            running_jobs=request.running_jobs,
            capabilities=request.capabilities,
            last_heartbeat_at=now,
        )
        self.runners[request.runner_id] = record
        return record

    def list_runners(self) -> list[RunnerRecord]:
        return list(self.runners.values())

    def mark_stale_runners_offline(self, *, stale_before: datetime) -> list[str]:
        marked: list[str] = []
        for record in self.runners.values():
            if (
                record.state == RunnerState.OFFLINE
                or record.last_heartbeat_at > stale_before
            ):
                continue
            record.state = RunnerState.OFFLINE
            marked.append(record.id)
        return marked

    def record_artifact(
        self, job_id: str, request: ArtifactCreateRequest
    ) -> ArtifactResponse:
        self.get_job(job_id)
        artifact = ArtifactResponse(
            id=self._next_artifact_id,
            job_id=job_id,
            trial_id=request.trial_id,
            kind=request.kind,
            storage_type=request.storage_type,
            storage_key=request.storage_key,
            size_bytes=request.size_bytes,
            relative_path=request.relative_path,
            checksum_sha256=request.checksum_sha256,
            etag=request.etag,
            content_type=request.content_type,
            uploaded_at=request.uploaded_at,
            metadata=request.metadata,
            created_at=_utcnow(),
        )
        self._next_artifact_id += 1
        self.artifacts.setdefault(job_id, []).append(artifact)
        return artifact

    def list_artifacts(self, job_id: str) -> list[ArtifactResponse]:
        self.get_job(job_id)
        return list(self.artifacts.get(job_id, []))

    def get_artifact(self, job_id: str, artifact_id: int) -> ArtifactResponse:
        for artifact in self.list_artifacts(job_id):
            if artifact.id == artifact_id:
                return artifact
        raise ValueError(str(artifact_id))

    def update_artifact_state(
        self,
        job_id: str,
        *,
        artifact_state: ArtifactState,
        error_message: str | None = None,
    ) -> JobRecord:
        record = self.get_job(job_id)
        record.artifact_state = artifact_state
        if error_message is not None:
            record.error_message = error_message
        record.updated_at = _utcnow()
        return record

    def update_input_state(
        self,
        job_id: str,
        *,
        input_state: InputState,
        materialized_inputs: list[MaterializedInputDataset] | None = None,
        error_message: str | None = None,
    ) -> JobRecord:
        record = self.get_job(job_id)
        record.input_state = input_state
        if materialized_inputs is not None:
            record.materialized_inputs = materialized_inputs
        if error_message is not None:
            record.error_message = error_message
        record.updated_at = _utcnow()
        return record

    def mark_input_materialization_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        materialized_inputs: list[MaterializedInputDataset] | None = None,
    ) -> JobRecord:
        record = self.get_job(job_id)
        now = _utcnow()
        record.state = JobState.FAILED
        record.input_state = InputState.FAILED
        if materialized_inputs is not None:
            record.materialized_inputs = materialized_inputs
        record.error_type = "input_materialization_failed"
        record.error_message = error_message
        record.updated_at = now
        record.finished_at = now
        return record


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _job_matches_query(record: JobRecord, request: JobQueryRequest) -> bool:
    if request.ids is not None and record.id not in request.ids:
        return False
    if request.states is not None and record.state not in request.states:
        return False
    if (
        request.input_states is not None
        and record.input_state not in request.input_states
    ):
        return False
    if (
        request.artifact_states is not None
        and record.artifact_state not in request.artifact_states
    ):
        return False
    if request.provider is not None and record.provider != request.provider:
        return False
    if request.runner_id is not None and record.runner_id != request.runner_id:
        return False
    if request.created_after is not None and record.created_at < request.created_after:
        return False
    if (
        request.created_before is not None
        and record.created_at > request.created_before
    ):
        return False
    if request.updated_after is not None and record.updated_at < request.updated_after:
        return False
    return not (
        request.updated_before is not None
        and record.updated_at > request.updated_before
    )


def _trial_matches_query(
    trial: TrialStatusResponse,
    request: TrialQueryRequest,
) -> bool:
    if request.job_id is not None and trial.job_id != request.job_id:
        return False
    if request.states is not None and trial.state not in request.states:
        return False
    if request.task_name is not None and trial.task_name != request.task_name:
        return False
    if request.agent_name is not None and trial.agent_name != request.agent_name:
        return False
    if request.model_name is not None and trial.model_name != request.model_name:
        return False
    if request.updated_after is not None and trial.updated_at < request.updated_after:
        return False
    return not (
        request.updated_before is not None and trial.updated_at > request.updated_before
    )


def _artifact_matches_query(
    artifact: ArtifactResponse,
    request: ArtifactQueryRequest,
) -> bool:
    if request.job_id is not None and artifact.job_id != request.job_id:
        return False
    if request.trial_id is not None and artifact.trial_id != request.trial_id:
        return False
    if request.kinds is not None and artifact.kind not in request.kinds:
        return False
    if (
        request.storage_types is not None
        and artifact.storage_type not in request.storage_types
    ):
        return False
    if (
        request.created_after is not None
        and artifact.created_at < request.created_after
    ):
        return False
    return not (
        request.created_before is not None
        and artifact.created_at > request.created_before
    )


def _matches_requirements(
    requirements: dict[str, Any],
    capabilities: dict[str, Any],
) -> bool:
    provider = requirements.get("provider")
    providers = capabilities.get("providers")
    if provider is not None and (
        not isinstance(providers, list) or provider not in providers
    ):
        return False

    required_features = requirements.get("required_features") or []
    features = set(capabilities.get("features") or [])
    if any(feature not in features for feature in required_features):
        return False

    required_labels = requirements.get("labels") or {}
    labels = capabilities.get("labels") or {}
    if not isinstance(required_labels, dict) or not isinstance(labels, dict):
        return False
    return all(labels.get(key) == value for key, value in required_labels.items())


def _is_artifact_retry_claimable(record: JobRecord, runner_id: str) -> bool:
    return (
        record.state
        in {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMED_OUT,
        }
        and record.artifact_state == ArtifactState.PENDING
        and record.runner_id == runner_id
    )


def _page_by_key(items: list, *, limit: int, cursor: str | None, key):
    after = _decode_cursor(cursor)
    filtered = [
        item for item in items if after is None or _cursor_key(key(item)) > after
    ]
    page = filtered[:limit]
    next_cursor = None
    if len(filtered) > limit and page:
        next_cursor = _encode_cursor(key(page[-1]))
    return page, next_cursor


def _cursor_key(value: tuple[datetime, str]) -> tuple[str, str]:
    first, second = value
    return first.isoformat(), second


def _encode_cursor(value: tuple[datetime, str]) -> str:
    raw = json.dumps(_cursor_key(value), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    decoded = base64.urlsafe_b64decode(cursor.encode("ascii"))
    raw = json.loads(decoded.decode("utf-8"))
    return str(raw[0]), str(raw[1])


def _trial_statuses_from_result_json(
    job_id: str,
    result_json: dict[str, Any] | None,
    *,
    updated_at: datetime,
) -> list[TrialStatusResponse] | None:
    if not isinstance(result_json, dict):
        return None
    trial_results = result_json.get("trial_results")
    if not isinstance(trial_results, list):
        return None

    rows: list[TrialStatusResponse] = []
    for index, trial_result in enumerate(trial_results):
        if not isinstance(trial_result, dict):
            continue
        rows.append(
            _trial_status_from_trial_result(
                job_id=job_id,
                trial_result=trial_result,
                index=index,
                updated_at=updated_at,
            )
        )
    return rows


def _trial_status_from_trial_result(
    *,
    job_id: str,
    trial_result: dict[str, Any],
    index: int,
    updated_at: datetime,
) -> TrialStatusResponse:
    agent_info = _dict_or_empty(trial_result.get("agent_info"))
    model_info = _dict_or_empty(agent_info.get("model_info"))
    exception_info = _dict_or_empty(trial_result.get("exception_info"))

    return TrialStatusResponse(
        id=_trial_id(job_id=job_id, trial_result=trial_result, index=index),
        job_id=job_id,
        state=_trial_state(trial_result),
        task_name=_str_or_none(trial_result.get("task_name")),
        agent_name=_str_or_none(agent_info.get("name")),
        model_name=_str_or_none(model_info.get("name")),
        reward=_primary_reward(trial_result),
        exception_type=_str_or_none(exception_info.get("exception_type")),
        result_json=trial_result,
        started_at=trial_result.get("started_at"),
        updated_at=updated_at,
        finished_at=trial_result.get("finished_at"),
    )


def _trial_id(
    *,
    job_id: str,
    trial_result: dict[str, Any],
    index: int,
) -> str:
    raw_id = trial_result.get("id")
    if raw_id is not None:
        return str(raw_id)
    return f"{job_id}:{index}"


def _trial_state(trial_result: dict[str, Any]) -> TrialState:
    exception_info = _dict_or_empty(trial_result.get("exception_info"))
    exception_type = exception_info.get("exception_type")
    if exception_type == "CancelledError":
        return TrialState.CANCELLED
    if exception_type is not None:
        return TrialState.FAILED
    if trial_result.get("finished_at") is not None:
        return TrialState.SUCCEEDED
    if trial_result.get("started_at") is not None:
        return TrialState.RUNNING
    return TrialState.PENDING


def _primary_reward(trial_result: dict[str, Any]) -> float | None:
    verifier_result = _dict_or_empty(trial_result.get("verifier_result"))
    rewards = _dict_or_empty(verifier_result.get("rewards"))
    reward = rewards.get("reward")
    if _is_number(reward):
        return float(reward)

    numeric_rewards = [float(value) for value in rewards.values() if _is_number(value)]
    if len(numeric_rewards) == 1:
        return numeric_rewards[0]
    return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
