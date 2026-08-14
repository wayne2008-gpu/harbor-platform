from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from harbor_service_contracts.states import JobState, RunnerState, TrialState


class ArtifactCreateRequest(BaseModel):
    kind: str
    storage_type: str
    storage_key: str
    trial_id: str | None = None
    size_bytes: int | None = None


class ArtifactResponse(BaseModel):
    id: int
    job_id: str
    kind: str
    storage_type: str
    storage_key: str
    trial_id: str | None = None
    size_bytes: int | None = None
    created_at: datetime


class JobCreateRequest(BaseModel):
    job_config: dict[str, Any]


class JobStatusResponse(BaseModel):
    id: str
    state: JobState
    job_config: dict[str, Any]
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
