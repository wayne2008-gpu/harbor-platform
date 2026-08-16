from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from harbor_service_contracts.states import (
    ArtifactState,
    InputState,
    JobState,
    RunnerState,
    TrialState,
)


class ArtifactCreateRequest(BaseModel):
    kind: str
    storage_type: str
    storage_key: str
    trial_id: str | None = None
    size_bytes: int | None = None
    relative_path: str | None = None
    checksum_sha256: str | None = None
    etag: str | None = None
    content_type: str | None = None
    uploaded_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactResponse(BaseModel):
    id: int
    job_id: str
    kind: str
    storage_type: str
    storage_key: str
    trial_id: str | None = None
    size_bytes: int | None = None
    relative_path: str | None = None
    checksum_sha256: str | None = None
    etag: str | None = None
    content_type: str | None = None
    uploaded_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ArtifactStateUpdateRequest(BaseModel):
    artifact_state: ArtifactState
    error_message: str | None = None


class ArtifactDownloadUrlResponse(BaseModel):
    url: str
    expires_in: int


class InputDataset(BaseModel):
    name: str
    source_type: str = "cos"
    uri: str
    version: str | None = None
    format: str = "tar.gz"
    checksum_sha256: str | None = None
    target: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaterializedInputDataset(BaseModel):
    name: str
    source_type: str
    uri: str
    version: str | None = None
    format: str
    checksum_sha256: str | None = None
    target: str
    local_path: str
    size_bytes: int | None = None
    state: InputState
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InputStateUpdateRequest(BaseModel):
    input_state: InputState
    materialized_inputs: list[MaterializedInputDataset] = Field(default_factory=list)
    error_message: str | None = None


class JobCreateRequest(BaseModel):
    job_config: dict[str, Any]
    input_datasets: list[InputDataset] = Field(default_factory=list)
    requirements: dict[str, Any] = Field(default_factory=dict)


class JobBatchGetRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


class JobQueryRequest(BaseModel):
    ids: list[str] | None = None
    states: list[JobState] | None = None
    input_states: list[InputState] | None = None
    artifact_states: list[ArtifactState] | None = None
    provider: str | None = None
    runner_id: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class TrialQueryRequest(BaseModel):
    job_id: str | None = None
    states: list[TrialState] | None = None
    task_name: str | None = None
    agent_name: str | None = None
    model_name: str | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ArtifactQueryRequest(BaseModel):
    job_id: str | None = None
    trial_id: str | None = None
    kinds: list[str] | None = None
    storage_types: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class JobCancelRequest(BaseModel):
    reason: str | None = None
    mode: str = "graceful"
    grace_period_sec: float | None = Field(default=None, ge=0)
    cancelled_by: str | None = None
    idempotency_key: str | None = None


class JobControlResponse(BaseModel):
    job_id: str
    state: JobState
    cancel_requested: bool = False
    cancel_mode: str | None = None
    cancel_reason: str | None = None
    cancel_grace_period_sec: float | None = None
    cancel_deadline_at: datetime | None = None


class JobRetryRequest(BaseModel):
    reason: str | None = None
    idempotency_key: str | None = None


class ArtifactRetryRequest(BaseModel):
    reason: str | None = None
    idempotency_key: str | None = None


class JobClaimRequest(BaseModel):
    runner_id: str
    max_jobs: int = Field(default=1, ge=1, le=100)
    lease_duration_sec: float = Field(default=300.0, ge=1)
    capabilities: dict[str, Any] | None = None


class JobStatusResponse(BaseModel):
    id: str
    state: JobState
    input_state: InputState = InputState.PENDING
    artifact_state: ArtifactState = ArtifactState.PENDING
    job_config: dict[str, Any]
    input_datasets: list[InputDataset] = Field(default_factory=list)
    materialized_inputs: list[MaterializedInputDataset] = Field(default_factory=list)
    requirements: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    runner_id: str | None = None
    cancel_requested_at: datetime | None = None
    cancel_reason: str | None = None
    cancel_mode: str | None = None
    cancel_grace_period_sec: float | None = None
    cancel_deadline_at: datetime | None = None
    cancelled_by: str | None = None
    started_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None
    result_json: dict[str, Any] | None = None
    parent_job_id: str | None = None
    root_job_id: str | None = None
    attempt: int = 1
    retry_reason: str | None = None


class TrialStatusResponse(BaseModel):
    id: str
    job_id: str
    state: TrialState
    task_name: str | None = None
    agent_name: str | None = None
    model_name: str | None = None
    reward: float | None = None
    exception_type: str | None = None
    result_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None


class JobPageResponse(BaseModel):
    items: list[JobStatusResponse]
    next_cursor: str | None = None
    limit: int


class TrialPageResponse(BaseModel):
    items: list[TrialStatusResponse]
    next_cursor: str | None = None
    limit: int


class ArtifactPageResponse(BaseModel):
    items: list[ArtifactResponse]
    next_cursor: str | None = None
    limit: int


class JobClaimedLease(BaseModel):
    job_id: str
    lease_id: str
    lease_expires_at: datetime
    action: str = "run"
    job: JobStatusResponse


class JobClaimResponse(BaseModel):
    claimed: list[JobClaimedLease] = Field(default_factory=list)


class JobLeaseRequest(BaseModel):
    runner_id: str
    lease_id: str
    lease_expires_at: datetime


class JobLeaseResponse(BaseModel):
    job_id: str
    acquired: bool
    state: JobState
    runner_id: str | None = None
    lease_id: str | None = None


class JobSnapshotRequest(BaseModel):
    runner_id: str
    state: JobState
    result_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None


class RunnerStatusResponse(BaseModel):
    id: str
    state: RunnerState
    running_jobs: int = 0
    capabilities: dict[str, Any] = Field(default_factory=dict)
    last_heartbeat_at: datetime


class RunnerHeartbeatRequest(BaseModel):
    runner_id: str
    running_jobs: int = 0
    state: RunnerState = RunnerState.ONLINE
    capabilities: dict[str, Any] = Field(default_factory=dict)


class RunnerHeartbeatResponse(BaseModel):
    runner_id: str
    state: RunnerState
    heartbeat_accepted: bool = True
