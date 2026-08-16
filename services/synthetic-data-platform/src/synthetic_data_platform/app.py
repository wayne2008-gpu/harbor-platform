import json
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from synthetic_data_platform.harbor_api import HarborApiClient
from synthetic_data_platform.repository import (
    InMemorySyntheticTaskRepository,
    SyntheticTaskRecord,
)


class SyntheticTaskCreateRequest(BaseModel):
    name: str
    harbor_job_config: dict[str, Any] | None = None
    harbor_job_name: str | None = None
    dataset_path: str | None = None
    dataset_name: str | None = None
    task_names: list[str] | None = None
    tasks: list[dict[str, Any]] | None = None
    input_datasets: list[dict[str, Any]] = Field(default_factory=list)
    environment: dict[str, Any] = Field(default_factory=lambda: {"type": "docker"})
    agent_name: str | None = None
    model_name: str | None = None
    n_concurrent_trials: int = Field(default=1, ge=1)
    artifacts: list[str | dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_job_source(self):
        if self.harbor_job_config is not None:
            return self
        if self.dataset_path is not None and self.dataset_name is not None:
            raise ValueError("Set only one of dataset_path or dataset_name.")
        if self.tasks is not None and (
            self.dataset_path is not None or self.dataset_name is not None
        ):
            raise ValueError("Set either tasks or a dataset source, not both.")
        if (
            self.tasks is None
            and self.dataset_path is None
            and self.dataset_name is None
            and not self.input_datasets
        ):
            raise ValueError(
                "Provide harbor_job_config, tasks, dataset_path, dataset_name, "
                "or input_datasets."
            )
        return self


class SyntheticTaskResponse(BaseModel):
    id: str
    name: str
    harbor_job_id: str
    state: str
    harbor_state: str | None = None


class NullHarborApiClient:
    def submit_job(
        self,
        _job_config: dict,
        *,
        input_datasets: list[dict] | None = None,
    ) -> str:
        raise RuntimeError("Harbor API client is not configured.")

    def get_job(self, _job_id: str) -> dict:
        raise RuntimeError("Harbor API client is not configured.")

    def list_artifacts(self, _job_id: str) -> list[dict]:
        raise RuntimeError("Harbor API client is not configured.")

    def list_trials(self, _job_id: str) -> list[dict]:
        raise RuntimeError("Harbor API client is not configured.")

    def list_trial_artifacts(self, _job_id: str, _trial_id: str) -> list[dict]:
        raise RuntimeError("Harbor API client is not configured.")

    def fetch_artifact_content(self, _job_id: str, _artifact_id: int) -> bytes:
        raise RuntimeError("Harbor API client is not configured.")

    def fetch_trial_trajectory(self, _job_id: str, _trial_id: str) -> Any:
        raise RuntimeError("Harbor API client is not configured.")


def create_app(
    *,
    repository: InMemorySyntheticTaskRepository | None = None,
    harbor_api_client: HarborApiClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Synthetic Data Platform")
    repo = repository or InMemorySyntheticTaskRepository()
    harbor_client = harbor_api_client or NullHarborApiClient()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/synthetic-tasks",
        response_model=SyntheticTaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_synthetic_task(
        request: SyntheticTaskCreateRequest,
    ) -> SyntheticTaskResponse:
        harbor_job_config = _build_harbor_job_config(request)
        harbor_job_id = harbor_client.submit_job(
            harbor_job_config,
            input_datasets=request.input_datasets,
        )
        record = repo.create(
            task_id=uuid4().hex,
            name=request.name,
            harbor_job_id=harbor_job_id,
        )
        return _response(record)

    @app.get("/synthetic-tasks/{task_id}", response_model=SyntheticTaskResponse)
    def get_synthetic_task(task_id: str) -> SyntheticTaskResponse:
        return _response(_get_or_404(repo, task_id))

    @app.get("/synthetic-tasks/{task_id}/samples")
    def get_samples(task_id: str) -> list[dict]:
        return list(_get_or_404(repo, task_id).samples)

    @app.get("/synthetic-tasks/{task_id}/harbor-job")
    def get_harbor_job(task_id: str) -> dict:
        record = _get_or_404(repo, task_id)
        return harbor_client.get_job(record.harbor_job_id)

    @app.get("/synthetic-tasks/{task_id}/results")
    def get_task_results(task_id: str) -> dict[str, Any]:
        record = _get_or_404(repo, task_id)
        harbor_job_id = record.harbor_job_id
        return {
            "task": _response(record).model_dump(mode="json"),
            "harbor_job": harbor_client.get_job(harbor_job_id),
            "trials": harbor_client.list_trials(harbor_job_id),
            "artifacts": harbor_client.list_artifacts(harbor_job_id),
        }

    @app.get("/synthetic-tasks/{task_id}/artifacts")
    def get_task_artifacts(task_id: str) -> list[dict]:
        record = _get_or_404(repo, task_id)
        return harbor_client.list_artifacts(record.harbor_job_id)

    @app.get("/synthetic-tasks/{task_id}/trials")
    def get_task_trials(task_id: str) -> list[dict]:
        record = _get_or_404(repo, task_id)
        return harbor_client.list_trials(record.harbor_job_id)

    @app.get("/synthetic-tasks/{task_id}/trials/{trial_id}/result")
    def get_trial_result(task_id: str, trial_id: str) -> dict:
        record = _get_or_404(repo, task_id)
        for trial in harbor_client.list_trials(record.harbor_job_id):
            if str(trial.get("id")) == trial_id:
                return trial
        raise HTTPException(status_code=404, detail="Trial result not found")

    @app.get("/synthetic-tasks/{task_id}/trials/{trial_id}/artifacts")
    def get_trial_artifacts(task_id: str, trial_id: str) -> list[dict]:
        record = _get_or_404(repo, task_id)
        return harbor_client.list_trial_artifacts(record.harbor_job_id, trial_id)

    @app.get("/synthetic-tasks/{task_id}/trials/{trial_id}/trajectory")
    def get_trial_trajectory(task_id: str, trial_id: str) -> Any:
        record = _get_or_404(repo, task_id)
        return harbor_client.fetch_trial_trajectory(record.harbor_job_id, trial_id)

    @app.post("/synthetic-tasks/{task_id}/sync", response_model=SyntheticTaskResponse)
    def sync_synthetic_task(task_id: str) -> SyntheticTaskResponse:
        record = _get_or_404(repo, task_id)
        harbor_job = harbor_client.get_job(record.harbor_job_id)
        harbor_state = str(harbor_job["state"])
        return _response(repo.sync_harbor_state(task_id, harbor_state=harbor_state))

    @app.post("/synthetic-tasks/{task_id}/ingest-samples")
    def ingest_samples(task_id: str) -> dict[str, int]:
        record = _get_or_404(repo, task_id)
        samples: list[dict] = []
        for artifact in harbor_client.list_artifacts(record.harbor_job_id):
            kind = str(artifact.get("kind") or "")
            if kind not in {"sample", "samples", "trial-result"}:
                continue
            content = harbor_client.fetch_artifact_content(
                record.harbor_job_id,
                int(artifact["id"]),
            )
            samples.extend(_samples_from_json_bytes(content, kind=kind))
        repo.add_samples(task_id, samples)
        return {"ingested": len(samples)}

    @app.post(
        "/synthetic-tasks/{task_id}/publish", response_model=SyntheticTaskResponse
    )
    def publish_task(task_id: str) -> SyntheticTaskResponse:
        try:
            return _response(repo.publish(task_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=404, detail="Synthetic task not found"
            ) from exc

    return app


def _build_harbor_job_config(request: SyntheticTaskCreateRequest) -> dict[str, Any]:
    if request.harbor_job_config is not None:
        return dict(request.harbor_job_config)

    job_config: dict[str, Any] = {
        "job_name": request.harbor_job_name or request.name,
        "n_concurrent_trials": request.n_concurrent_trials,
        "environment": request.environment,
    }

    if request.tasks is not None:
        job_config["tasks"] = request.tasks
    elif request.dataset_path is not None or request.dataset_name is not None:
        dataset: dict[str, Any] = {}
        if request.dataset_path is not None:
            dataset["path"] = request.dataset_path
        if request.dataset_name is not None:
            dataset["name"] = request.dataset_name
        if request.task_names is not None:
            dataset["task_names"] = request.task_names
        job_config["datasets"] = [dataset]

    agent_config: dict[str, Any] = {}
    if request.agent_name is not None:
        agent_config["name"] = request.agent_name
    if request.model_name is not None:
        agent_config["model_name"] = request.model_name
    if agent_config:
        job_config["agents"] = [agent_config]

    if request.artifacts:
        job_config["artifacts"] = request.artifacts

    return job_config


def _samples_from_json_bytes(content: bytes, *, kind: str) -> list[dict]:
    data = json.loads(content.decode("utf-8"))
    if kind == "trial-result":
        if not isinstance(data, dict):
            return []
        samples = data.get("samples")
        if isinstance(samples, list):
            return [item for item in samples if isinstance(item, dict)]
        return []

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        samples = data.get("samples")
        if isinstance(samples, list):
            return [item for item in samples if isinstance(item, dict)]
        return [data]
    return []


def _get_or_404(
    repo: InMemorySyntheticTaskRepository,
    task_id: str,
) -> SyntheticTaskRecord:
    try:
        return repo.get(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Synthetic task not found") from exc


def _response(record: SyntheticTaskRecord) -> SyntheticTaskResponse:
    return SyntheticTaskResponse(
        id=record.id,
        name=record.name,
        harbor_job_id=record.harbor_job_id,
        state=record.state.value,
        harbor_state=record.harbor_state,
    )
