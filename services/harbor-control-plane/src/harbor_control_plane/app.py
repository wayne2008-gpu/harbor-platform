from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import Response
from harbor.models.job.config import JobConfig
from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactDownloadUrlResponse,
    ArtifactPageResponse,
    ArtifactQueryRequest,
    ArtifactResponse,
    ArtifactRetryRequest,
    ArtifactStateUpdateRequest,
    InputState,
    InputStateUpdateRequest,
    JobBatchGetRequest,
    JobCancelRequest,
    JobClaimRequest,
    JobClaimResponse,
    JobControlResponse,
    JobCreateRequest,
    JobDispatchMessage,
    JobDispatchRouting,
    JobLeaseRequest,
    JobLeaseResponse,
    JobPageResponse,
    JobQueryRequest,
    JobRetryRequest,
    JobSnapshotRequest,
    JobStatusResponse,
    RunnerHeartbeatRequest,
    RunnerHeartbeatResponse,
    RunnerStatusResponse,
    TrialPageResponse,
    TrialQueryRequest,
    TrialStatusResponse,
)
from pydantic import ValidationError

from harbor_control_plane.artifact_resolver import (
    ArtifactResolver,
    RunnerLocalArtifactResolver,
    read_artifact_json,
)
from harbor_control_plane.publisher import InMemoryJobPublisher
from harbor_control_plane.repository import InMemoryJobRepository, JobNotFoundError


def create_app(
    *,
    repository: Any | None = None,
    publisher: InMemoryJobPublisher | None = None,
    artifact_allowed_root: Path | None = None,
    artifact_resolver: ArtifactResolver | None = None,
) -> FastAPI:
    app = FastAPI(title="Harbor Control Plane")
    repo = repository or InMemoryJobRepository()
    job_publisher = publisher or InMemoryJobPublisher()
    resolver = artifact_resolver
    if resolver is None and artifact_allowed_root is not None:
        resolver = RunnerLocalArtifactResolver(allowed_root=artifact_allowed_root)

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
        requirements = _job_requirements(
            provider=provider,
            input_datasets=request.input_datasets,
            requested=request.requirements,
        )
        job_id = uuid4().hex
        record = repo.create_job(
            job_id=job_id,
            job_config=resolved_config,
            input_datasets=request.input_datasets,
            requirements=requirements,
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

    @app.post("/jobs/batch-get", response_model=list[JobStatusResponse])
    def batch_get_jobs(request: JobBatchGetRequest) -> list[JobStatusResponse]:
        return repo.batch_get_jobs(request)

    @app.post("/jobs/query", response_model=JobPageResponse)
    def query_jobs(request: JobQueryRequest) -> JobPageResponse:
        return repo.query_jobs(request)

    @app.post("/trials/query", response_model=TrialPageResponse)
    def query_trials(request: TrialQueryRequest) -> TrialPageResponse:
        return repo.query_trials(request)

    @app.post("/artifacts/query", response_model=ArtifactPageResponse)
    def query_artifacts(request: ArtifactQueryRequest) -> ArtifactPageResponse:
        return repo.query_artifacts(request)

    @app.get("/jobs/{job_id}/trials", response_model=list[TrialStatusResponse])
    def get_job_trials(job_id: str) -> list[TrialStatusResponse]:
        try:
            return repo.list_trials(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
    def cancel_job(
        job_id: str,
        request: JobCancelRequest | None = None,
    ) -> JobStatusResponse:
        try:
            return repo.request_cancel(
                job_id, request or JobCancelRequest()
            ).to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post("/jobs/{job_id}/retry", response_model=JobStatusResponse)
    def retry_job(job_id: str, request: JobRetryRequest) -> JobStatusResponse:
        retry = None
        try:
            retry = repo.retry_job(job_id, new_job_id=uuid4().hex, request=request)
            job_publisher.publish_job(
                JobDispatchMessage(
                    message_id=uuid4().hex,
                    job_id=retry.id,
                    routing=JobDispatchRouting(provider=retry.provider),
                )
            )
            return retry.to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        except Exception as exc:
            if retry is not None:
                repo.mark_dispatch_failed(retry.id, error_message=str(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to publish job retry dispatch message",
            ) from exc

    @app.post("/jobs/{job_id}/artifacts/retry", response_model=JobStatusResponse)
    def retry_artifacts(
        job_id: str,
        request: ArtifactRetryRequest,
    ) -> JobStatusResponse:
        try:
            return repo.request_artifact_retry(job_id, request).to_response()
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

    @app.post("/internal/jobs/claim", response_model=JobClaimResponse)
    def claim_jobs(request: JobClaimRequest) -> JobClaimResponse:
        return repo.claim_jobs(request)

    @app.get("/internal/jobs/{job_id}/control", response_model=JobControlResponse)
    def get_job_control(job_id: str) -> JobControlResponse:
        try:
            return repo.get_job_control(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

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
    def apply_job_snapshot(
        job_id: str, request: JobSnapshotRequest
    ) -> JobStatusResponse:
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

    @app.post(
        "/internal/jobs/{job_id}/artifact-state",
        response_model=JobStatusResponse,
    )
    def update_artifact_state(
        job_id: str,
        request: ArtifactStateUpdateRequest,
    ) -> JobStatusResponse:
        try:
            return repo.update_artifact_state(
                job_id,
                artifact_state=request.artifact_state,
                error_message=request.error_message,
            ).to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.post(
        "/internal/jobs/{job_id}/input-state",
        response_model=JobStatusResponse,
    )
    def update_input_state(
        job_id: str,
        request: InputStateUpdateRequest,
    ) -> JobStatusResponse:
        try:
            if request.input_state == InputState.FAILED:
                return repo.mark_input_materialization_failed(
                    job_id,
                    error_message=request.error_message
                    or "Input materialization failed",
                    materialized_inputs=request.materialized_inputs,
                ).to_response()
            return repo.update_input_state(
                job_id,
                input_state=request.input_state,
                materialized_inputs=request.materialized_inputs,
                error_message=request.error_message,
            ).to_response()
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/jobs/{job_id}/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(job_id: str) -> list[ArtifactResponse]:
        try:
            return repo.list_artifacts(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get(
        "/jobs/{job_id}/trials/{trial_id}/artifacts",
        response_model=list[ArtifactResponse],
    )
    def list_trial_artifacts(
        job_id: str,
        trial_id: str,
    ) -> list[ArtifactResponse]:
        try:
            return [
                artifact
                for artifact in repo.list_artifacts(job_id)
                if artifact.trial_id == trial_id
            ]
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/jobs/{job_id}/artifacts/{artifact_id}/content")
    def get_artifact_content(job_id: str, artifact_id: int) -> Response:
        if resolver is None:
            raise HTTPException(status_code=404, detail="Artifact proxy is disabled")
        artifact = _get_artifact_or_404(repo, job_id, artifact_id)
        return resolver.content_response(artifact)

    @app.get(
        "/jobs/{job_id}/artifacts/{artifact_id}/download-url",
        response_model=ArtifactDownloadUrlResponse,
    )
    def get_artifact_download_url(
        job_id: str,
        artifact_id: int,
    ) -> ArtifactDownloadUrlResponse:
        if resolver is None:
            raise HTTPException(status_code=404, detail="Artifact proxy is disabled")
        artifact = _get_artifact_or_404(repo, job_id, artifact_id)
        return resolver.download_url(artifact)

    @app.get("/jobs/{job_id}/trials/{trial_id}/trajectory")
    def get_trial_trajectory(job_id: str, trial_id: str) -> Any:
        if resolver is None:
            raise HTTPException(status_code=404, detail="Artifact proxy is disabled")
        try:
            artifacts = repo.list_artifacts(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        trajectory = _select_trajectory_artifact(artifacts, trial_id=trial_id)
        if trajectory is None:
            raise HTTPException(status_code=404, detail="Trajectory artifact not found")
        return read_artifact_json(resolver=resolver, artifact=trajectory)

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


def _job_requirements(
    *,
    provider: str | None,
    input_datasets: list,
    requested: dict[str, Any],
) -> dict[str, Any]:
    requirements = dict(requested)
    if provider is not None:
        requirements.setdefault("provider", provider)
    required_features = set(requirements.get("required_features") or [])
    if any(
        getattr(dataset, "source_type", None) == "cos" for dataset in input_datasets
    ):
        required_features.add("cos-input")
    if required_features:
        requirements["required_features"] = sorted(required_features)
    requirements.setdefault("labels", {})
    return requirements


def _get_job_or_404(repo: Any, job_id: str):
    try:
        return repo.get_job(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


def _get_artifact_or_404(repo: Any, job_id: str, artifact_id: int) -> ArtifactResponse:
    try:
        return repo.get_artifact(job_id, artifact_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc


def _select_trajectory_artifact(
    artifacts: list[ArtifactResponse],
    *,
    trial_id: str,
) -> ArtifactResponse | None:
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.trial_id == trial_id and artifact.kind == "trajectory"
    ]
    if not candidates:
        return None

    def priority(artifact: ArtifactResponse) -> tuple[int, str]:
        relative_path = artifact.relative_path or artifact.storage_key
        if relative_path.endswith(("/agent/trajectory.json", "agent/trajectory.json")):
            return (0, relative_path)
        return (1, relative_path)

    return min(candidates, key=priority)
