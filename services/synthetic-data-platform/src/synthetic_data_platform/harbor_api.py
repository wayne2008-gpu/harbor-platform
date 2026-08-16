from typing import Any, Protocol

import httpx


class HarborApiClient(Protocol):
    def submit_job(
        self,
        job_config: dict,
        *,
        input_datasets: list[dict] | None = None,
    ) -> str: ...

    def get_job(self, job_id: str) -> dict: ...

    def list_artifacts(self, job_id: str) -> list[dict]: ...

    def list_trials(self, job_id: str) -> list[dict]: ...

    def list_trial_artifacts(self, job_id: str, trial_id: str) -> list[dict]: ...

    def fetch_artifact_content(self, job_id: str, artifact_id: int) -> bytes: ...

    def fetch_trial_trajectory(self, job_id: str, trial_id: str) -> Any: ...


class HttpHarborApiClient:
    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def submit_job(
        self,
        job_config: dict,
        *,
        input_datasets: list[dict] | None = None,
    ) -> str:
        response = httpx.post(
            f"{self.base_url}/jobs",
            json={
                "job_config": job_config,
                "input_datasets": input_datasets or [],
            },
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return str(response.json()["id"])

    def get_job(self, job_id: str) -> dict:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return dict(response.json())

    def list_artifacts(self, job_id: str) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/artifacts",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return list(response.json())

    def list_trials(self, job_id: str) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/trials",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return list(response.json())

    def list_trial_artifacts(self, job_id: str, trial_id: str) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/trials/{trial_id}/artifacts",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return list(response.json())

    def fetch_artifact_content(self, job_id: str, artifact_id: int) -> bytes:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/artifacts/{artifact_id}/content",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return response.content

    def fetch_trial_trajectory(self, job_id: str, trial_id: str) -> Any:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/trials/{trial_id}/trajectory",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return response.json()
