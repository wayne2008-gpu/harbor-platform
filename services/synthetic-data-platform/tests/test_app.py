from fastapi.testclient import TestClient

from synthetic_data_platform.app import create_app
from synthetic_data_platform.repository import InMemorySyntheticTaskRepository


class FakeHarborApiClient:
    def __init__(self) -> None:
        self.submitted_job_configs = []
        self.artifacts = [
            {"id": 1, "kind": "samples"},
            {"id": 2, "kind": "agent-log"},
        ]
        self.artifact_contents = {
            1: b'{"samples": [{"text": "a"}, {"text": "b"}]}',
        }
        self.job_status = {
            "id": "harbor-job-1",
            "state": "running",
            "result_json": None,
        }
        self.listed_job_ids = []
        self.fetched_artifact_ids = []

    def submit_job(self, job_config: dict) -> str:
        self.submitted_job_configs.append(job_config)
        return "harbor-job-1"

    def get_job(self, job_id: str) -> dict:
        assert job_id == "harbor-job-1"
        return dict(self.job_status)

    def list_artifacts(self, job_id: str) -> list[dict]:
        assert job_id == "harbor-job-1"
        self.listed_job_ids.append(job_id)
        return self.artifacts

    def fetch_artifact_content(self, job_id: str, artifact_id: int) -> bytes:
        assert job_id == "harbor-job-1"
        self.fetched_artifact_ids.append(artifact_id)
        return self.artifact_contents[artifact_id]


def _client():
    repo = InMemorySyntheticTaskRepository()
    harbor = FakeHarborApiClient()
    return TestClient(create_app(repository=repo, harbor_api_client=harbor)), harbor


def test_create_task_submits_harbor_job_and_stores_mapping() -> None:
    client, harbor = _client()

    response = client.post(
        "/synthetic-tasks",
        json={
            "name": "dataset-a",
            "harbor_job_config": {
                "job_name": "synthetic-job",
                "environment": {"type": "ags"},
            },
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["name"] == "dataset-a"
    assert body["harbor_job_id"] == "harbor-job-1"
    assert body["state"] == "submitted"
    assert body["harbor_state"] is None
    assert harbor.submitted_job_configs == [
        {"job_name": "synthetic-job", "environment": {"type": "ags"}}
    ]

    assert client.get(f"/synthetic-tasks/{body['id']}").json() == body
    assert client.get(f"/synthetic-tasks/{body['id']}/samples").json() == []


def test_create_task_generates_harbor_job_config_from_business_fields() -> None:
    client, harbor = _client()

    response = client.post(
        "/synthetic-tasks",
        json={
            "name": "dataset-a",
            "harbor_job_name": "synthetic-job",
            "dataset_path": "/datasets/synthetic-a",
            "task_names": ["task-*"],
            "environment": {"type": "tke"},
            "agent_name": "codex",
            "model_name": "gpt-5",
            "n_concurrent_trials": 2,
            "artifacts": ["artifacts/samples.json"],
        },
    )

    assert response.status_code == 202
    assert harbor.submitted_job_configs == [
        {
            "job_name": "synthetic-job",
            "n_concurrent_trials": 2,
            "environment": {"type": "tke"},
            "datasets": [
                {
                    "path": "/datasets/synthetic-a",
                    "task_names": ["task-*"],
                }
            ],
            "agents": [{"name": "codex", "model_name": "gpt-5"}],
            "artifacts": ["artifacts/samples.json"],
        }
    ]


def test_create_task_requires_direct_config_or_generation_source() -> None:
    client, harbor = _client()

    response = client.post("/synthetic-tasks", json={"name": "dataset-a"})

    assert response.status_code == 422
    assert harbor.submitted_job_configs == []


def test_get_and_sync_harbor_job_status() -> None:
    client, harbor = _client()
    task = client.post(
        "/synthetic-tasks",
        json={"name": "dataset-a", "harbor_job_config": {"job_name": "job"}},
    ).json()

    harbor_job = client.get(f"/synthetic-tasks/{task['id']}/harbor-job")
    assert harbor_job.status_code == 200
    assert harbor_job.json()["state"] == "running"

    synced = client.post(f"/synthetic-tasks/{task['id']}/sync")
    assert synced.status_code == 200
    assert synced.json()["state"] == "running"
    assert synced.json()["harbor_state"] == "running"

    harbor.job_status["state"] = "succeeded"
    synced = client.post(f"/synthetic-tasks/{task['id']}/sync")
    assert synced.json()["state"] == "succeeded"
    assert synced.json()["harbor_state"] == "succeeded"


def test_publish_task() -> None:
    client, _harbor = _client()
    task = client.post(
        "/synthetic-tasks",
        json={"name": "dataset-a", "harbor_job_config": {"job_name": "job"}},
    ).json()

    response = client.post(f"/synthetic-tasks/{task['id']}/publish")

    assert response.status_code == 200
    assert response.json()["state"] == "published"


def test_ingest_samples_reads_harbor_artifacts() -> None:
    client, _harbor = _client()
    task = client.post(
        "/synthetic-tasks",
        json={"name": "dataset-a", "harbor_job_config": {"job_name": "job"}},
    ).json()

    response = client.post(f"/synthetic-tasks/{task['id']}/ingest-samples")

    assert response.status_code == 200
    assert response.json() == {"ingested": 2}
    assert client.get(f"/synthetic-tasks/{task['id']}/samples").json() == [
        {"text": "a"},
        {"text": "b"},
    ]


def test_ingest_samples_ignores_job_result_artifacts() -> None:
    client, harbor = _client()
    harbor.artifacts = [
        {"id": 1, "kind": "result"},
        {"id": 2, "kind": "trial-result"},
        {"id": 3, "kind": "trial-result"},
    ]
    harbor.artifact_contents = {
        1: b'{"id": "job-1", "trial_results": []}',
        2: b'{"id": "trial-1", "reward": 1}',
        3: b'{"samples": [{"text": "from-trial"}]}',
    }
    task = client.post(
        "/synthetic-tasks",
        json={"name": "dataset-a", "harbor_job_config": {"job_name": "job"}},
    ).json()

    response = client.post(f"/synthetic-tasks/{task['id']}/ingest-samples")

    assert response.status_code == 200
    assert response.json() == {"ingested": 1}
    assert client.get(f"/synthetic-tasks/{task['id']}/samples").json() == [
        {"text": "from-trial"}
    ]


def test_succeeded_task_ingests_samples_via_harbor_artifact_endpoints() -> None:
    client, harbor = _client()
    harbor.job_status = {
        "id": "harbor-job-1",
        "state": "succeeded",
        "result_json": {"n_completed_trials": 1},
    }
    harbor.artifacts = [
        {
            "id": 10,
            "kind": "artifact-manifest",
            "storage_key": "artifacts/runner-manifest.json",
        },
        {"id": 11, "kind": "result", "storage_key": "result.json"},
        {"id": 12, "kind": "trial-result", "trial_id": "trial-a"},
        {"id": 13, "kind": "samples", "trial_id": "trial-a"},
        {"id": 14, "kind": "agent-log", "trial_id": "trial-a"},
    ]
    harbor.artifact_contents = {
        12: b'{"id": "trial-a", "samples": [{"text": "from-trial-result"}]}',
        13: b'[{"text": "from-samples-file"}]',
    }
    task = client.post(
        "/synthetic-tasks",
        json={"name": "dataset-a", "harbor_job_config": {"job_name": "job"}},
    ).json()

    synced = client.post(f"/synthetic-tasks/{task['id']}/sync")
    response = client.post(f"/synthetic-tasks/{task['id']}/ingest-samples")

    assert synced.status_code == 200
    assert synced.json()["state"] == "succeeded"
    assert response.status_code == 200
    assert response.json() == {"ingested": 2}
    assert harbor.listed_job_ids == ["harbor-job-1"]
    assert harbor.fetched_artifact_ids == [12, 13]
    assert client.get(f"/synthetic-tasks/{task['id']}/samples").json() == [
        {"text": "from-trial-result"},
        {"text": "from-samples-file"},
    ]
