from typing import Protocol

import httpx


class HarborApiClient(Protocol):
    def submit_job(self, job_config: dict) -> str: ...

    def get_job(self, job_id: str) -> dict: ...

    def list_artifacts(self, job_id: str) -> list[dict]: ...

    def fetch_artifact_content(self, job_id: str, artifact_id: int) -> bytes: ...


class HttpHarborApiClient:
    def __init__(self, base_url: str, *, timeout_sec: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def submit_job(self, job_config: dict) -> str:
        response = httpx.post(
            f"{self.base_url}/jobs",
            json={"job_config": job_config},
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

    def fetch_artifact_content(self, job_id: str, artifact_id: int) -> bytes:
        response = httpx.get(
            f"{self.base_url}/jobs/{job_id}/artifacts/{artifact_id}/content",
            timeout=self.timeout_sec,
        )
        response.raise_for_status()
        return response.content
