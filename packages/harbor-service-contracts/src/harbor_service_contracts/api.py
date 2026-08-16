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


class JobStatusResponse(BaseModel):
    id: str
    state: JobState
    input_state: InputState = InputState.PENDING
    artifact_state: ArtifactState = ArtifactState.PENDING
    job_config: dict[str, Any]
    input_datasets: list[InputDataset] = Field(default_factory=list)
    materialized_inputs: list[MaterializedInputDataset] = Field(default_factory=list)
    provider: str | None = None
    runner_id: str | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    updated_at: datetime
    finished_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None
    result_json: dict[str, Any] | None = None


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
