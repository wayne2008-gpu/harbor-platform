from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from harbor.models.job.config import JobConfig
from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactResponse,
    JobCreateRequest,
    JobDispatchMessage,
    JobDispatchRouting,
    JobLeaseRequest,
    JobLeaseResponse,
    JobSnapshotRequest,
    JobStatusResponse,
    RunnerHeartbeatRequest,
    RunnerHeartbeatResponse,
    RunnerStatusResponse,
    TrialStatusResponse,
)
from pydantic import ValidationError

from harbor_control_plane.artifact_proxy import serve_runner_local_artifact
from harbor_control_plane.publisher import InMemoryJobPublisher
from harbor_control_plane.repository import InMemoryJobRepository, JobNotFoundError


def create_app(
    *,
    repository: Any | None = None,
    publisher: InMemoryJobPublisher | None = None,
    artifact_allowed_root: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Harbor Control Plane")
    repo = repository or InMemoryJobRepository()
    job_publisher = publisher or InMemoryJobPublisher()

    app.state.repository = repo
    app.state.publisher = job_publisher

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/jobs",
        response_model=JobStatusResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_job(request: JobCreateRequest) -> JobStatusResponse:
        resolved_config = _resolve_job_config(request.job_config)
        provider = _provider_from_job_config(resolved_config)
        job_id = uuid4().hex
        record = repo.create_job(
            job_id=job_id,
            job_config=resolved_config,
            provider=provider,
        )
        try:
            job_publisher.publish_job(
                JobDispatchMessage(
                    message_id=uuid4().hex,
                    job_id=job_id,
                    routing=JobDispatchRouting(provider=provider),
                )
            )
        except Exception as exc:
            repo.mark_dispatch_failed(job_id, error_message=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to publish job dispatch message",
            ) from exc
        return record.to_response()

    @app.get("/jobs/{job_id}", response_model=JobStatusResponse)
    def get_job(job_id: str) -> JobStatusResponse:
        return _get_job_or_404(repo, job_id).to_response()

    @app.get("/jobs/{job_id}/trials", response_model=list[TrialStatusResponse])
    def get_job_trials(job_id: str) -> list[TrialStatusResponse]:
        try:
            return repo.list_trials(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
    def cancel_job(job_id: str) -> JobStatusResponse:
        try:
            return repo.request_cancel(job_id).to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/internal/jobs/queued", response_model=list[str])
    def list_queued_jobs(
        limit: int = Query(default=10, ge=1, le=100),
    ) -> list[str]:
        return repo.list_queued_job_ids(limit=limit)

    @app.post("/internal/jobs/requeue-expired-leases", response_model=list[str])
    def requeue_expired_leases() -> list[str]:
        return repo.requeue_expired_leases()

    @app.post("/internal/jobs/{job_id}/lease", response_model=JobLeaseResponse)
    def acquire_job_lease(job_id: str, request: JobLeaseRequest) -> JobLeaseResponse:
        _get_job_or_404(repo, job_id)
        acquired = repo.acquire_lease(
            job_id=job_id,
            runner_id=request.runner_id,
            lease_id=request.lease_id,
            lease_expires_at=request.lease_expires_at,
        )
        record = repo.get_job(job_id)
        return JobLeaseResponse(
            job_id=job_id,
            acquired=acquired,
            state=record.state,
            runner_id=record.runner_id,
            lease_id=record.lease_id,
        )

    @app.post("/internal/jobs/{job_id}/snapshot", response_model=JobStatusResponse)
    def apply_job_snapshot(job_id: str, request: JobSnapshotRequest) -> JobStatusResponse:
        try:
            return repo.apply_snapshot(job_id, request).to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc


    @app.post(
        "/internal/jobs/{job_id}/artifacts",
        response_model=ArtifactResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def record_artifact(
        job_id: str, request: ArtifactCreateRequest
    ) -> ArtifactResponse:
        try:
            return repo.record_artifact(job_id, request)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/jobs/{job_id}/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(job_id: str) -> list[ArtifactResponse]:
        try:
            return repo.list_artifacts(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc


    @app.get("/jobs/{job_id}/artifacts/{artifact_id}/content")
    def get_artifact_content(job_id: str, artifact_id: int) -> FileResponse:
        if artifact_allowed_root is None:
            raise HTTPException(status_code=404, detail="Artifact proxy is disabled")
        try:
            artifact = repo.get_artifact(job_id, artifact_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found") from exc
        if artifact.storage_type != "runner-local":
            raise HTTPException(status_code=400, detail="Artifact is not runner-local")
        return serve_runner_local_artifact(
            storage_key=artifact.storage_key,
            allowed_root=artifact_allowed_root,
        )

    @app.post("/runners/heartbeat", response_model=RunnerHeartbeatResponse)
    def heartbeat_runner(request: RunnerHeartbeatRequest) -> RunnerHeartbeatResponse:
        record = repo.heartbeat_runner(request)
        return RunnerHeartbeatResponse(runner_id=record.id, state=record.state)

    @app.get("/runners", response_model=list[RunnerStatusResponse])
    def list_runners(
        stale_after_sec: int | None = Query(default=60, ge=1),
    ) -> list[RunnerStatusResponse]:
        if stale_after_sec is not None:
            repo.mark_stale_runners_offline(
                stale_before=datetime.now(UTC) - timedelta(seconds=stale_after_sec)
            )
        return [runner.to_response() for runner in repo.list_runners()]

    return app


def _resolve_job_config(raw_config: dict[str, Any]) -> dict[str, Any]:
    try:
        config = JobConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(include_url=False, include_input=False),
        ) from exc
    return config.model_dump(mode="json", exclude_defaults=True)


def _provider_from_job_config(config: dict[str, Any]) -> str | None:
    environment = config.get("environment")
    if not isinstance(environment, dict):
        return None
    provider = environment.get("type")
    if provider is None:
        return None
    return str(provider)


def _get_job_or_404(repo: Any, job_id: str):
    try:
        return repo.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
