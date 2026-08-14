from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from harbor_service_contracts import JobDispatchMessage, JobState, RunnerState

from harbor_control_plane.app import create_app
from harbor_control_plane.publisher import InMemoryJobPublisher
from harbor_control_plane.repository import InMemoryJobRepository


class FailingJobPublisher(InMemoryJobPublisher):
    def publish_job(self, message: JobDispatchMessage) -> None:
        raise RuntimeError("topic unavailable")


def _client(*, artifact_allowed_root=None, publisher=None):
    repo = InMemoryJobRepository()
    publisher = publisher or InMemoryJobPublisher()
    return (
        TestClient(
            create_app(
                repository=repo,
                publisher=publisher,
                artifact_allowed_root=artifact_allowed_root,
            )
        ),
        repo,
        publisher,
    )


def _trial_result_json() -> dict:
    return {
        "id": "trial-1",
        "task_name": "task-a",
        "trial_name": "task-a__abc1234",
        "agent_info": {
            "name": "codex",
            "version": "1",
            "model_info": {"name": "gpt-5"},
        },
        "verifier_result": {"rewards": {"reward": 1}},
        "started_at": "2026-08-14T00:00:00Z",
        "finished_at": "2026-08-14T00:01:00Z",
    }


def test_health() -> None:
    client, _repo, _publisher = _client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_job_stores_job_and_publishes_dispatch_message() -> None:
    client, repo, publisher = _client()

    response = client.post(
        "/jobs",
        json={"job_config": {"job_name": "api-smoke", "environment": {"type": "ags"}}},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    job_id = body["id"]
    assert body["state"] == "queued"
    assert body["provider"] == "ags"
    assert repo.get_job(job_id).job_config["job_name"] == "api-smoke"
    assert len(publisher.messages) == 1
    assert publisher.messages[0].job_id == job_id
    assert publisher.messages[0].routing.provider == "ags"


def test_create_job_rejects_invalid_harbor_job_config_without_publishing() -> None:
    client, _repo, publisher = _client()

    response = client.post(
        "/jobs",
        json={"job_config": {"n_concurrent_trials": 0}},
    )

    assert response.status_code == 422
    assert publisher.messages == []


def test_create_job_marks_job_failed_when_dispatch_publish_fails() -> None:
    client, repo, _publisher = _client(publisher=FailingJobPublisher())

    response = client.post(
        "/jobs",
        json={"job_config": {"job_name": "api-smoke", "environment": {"type": "ags"}}},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Failed to publish job dispatch message"}
    job_id = next(iter(repo.jobs))
    record = repo.get_job(job_id)
    assert record.state == JobState.FAILED
    assert record.error_type == "dispatch_failed"
    assert record.error_message == "topic unavailable"
    assert record.finished_at is not None
    assert client.get("/internal/jobs/queued").json() == []


def test_get_cancel_trials_and_runners_endpoints() -> None:
    client, _repo, _publisher = _client()
    created = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()
    job_id = created["id"]

    assert client.get(f"/jobs/{job_id}").json()["state"] == "queued"
    assert client.get(f"/jobs/{job_id}/trials").json() == []

    cancelled = client.post(f"/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"

    runners = client.get("/runners")
    assert runners.status_code == 200
    assert runners.json() == []


def test_internal_queued_jobs_endpoint_requeues_expired_leases() -> None:
    client, repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    client.post(
        f"/internal/jobs/{job_id}/lease",
        json={
            "runner_id": "runner-1",
            "lease_id": "lease-1",
            "lease_expires_at": "2000-01-01T00:00:00Z",
        },
    )

    response = client.get("/internal/jobs/queued")

    assert response.status_code == 200
    assert response.json() == [job_id]
    record = repo.get_job(job_id)
    assert record.state == JobState.QUEUED
    assert record.runner_id is None
    assert record.lease_id is None
    assert record.lease_expires_at is None


def test_internal_requeue_expired_leases_endpoint_returns_requeued_ids() -> None:
    client, _repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    client.post(
        f"/internal/jobs/{job_id}/lease",
        json={
            "runner_id": "runner-1",
            "lease_id": "lease-1",
            "lease_expires_at": "2000-01-01T00:00:00Z",
        },
    )

    response = client.post("/internal/jobs/requeue-expired-leases")

    assert response.status_code == 200
    assert response.json() == [job_id]


def test_list_runners_marks_stale_heartbeats_offline() -> None:
    client, repo, _publisher = _client()
    heartbeat = client.post(
        "/runners/heartbeat",
        json={"runner_id": "runner-1", "running_jobs": 0},
    )
    assert heartbeat.status_code == 200
    repo.runners["runner-1"].last_heartbeat_at = datetime.now(UTC) - timedelta(
        seconds=120
    )

    response = client.get("/runners", params={"stale_after_sec": 60})

    assert response.status_code == 200
    assert response.json()[0]["state"] == RunnerState.OFFLINE.value


def test_internal_queued_jobs_endpoint_returns_only_available_queued_jobs() -> None:
    client, _repo, _publisher = _client()
    first = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    second = client.post("/jobs", json={"job_config": {"job_name": "job-2"}}).json()[
        "id"
    ]
    third = client.post("/jobs", json={"job_config": {"job_name": "job-3"}}).json()[
        "id"
    ]

    assert client.get("/internal/jobs/queued", params={"limit": 2}).json() == [
        first,
        second,
    ]

    client.post(f"/jobs/{second}/cancel")
    client.post(
        f"/internal/jobs/{first}/lease",
        json={
            "runner_id": "runner-1",
            "lease_id": "lease-1",
            "lease_expires_at": "2099-01-01T00:05:00Z",
        },
    )

    response = client.get("/internal/jobs/queued", params={"limit": 10})

    assert response.status_code == 200
    assert response.json() == [third]


def test_runner_heartbeat_lease_and_snapshot_flow() -> None:
    client, _repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]

    heartbeat = client.post(
        "/runners/heartbeat",
        json={"runner_id": "runner-1", "running_jobs": 0},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["state"] == "online"
    assert client.get("/runners").json()[0]["id"] == "runner-1"

    lease = client.post(
        f"/internal/jobs/{job_id}/lease",
        json={
            "runner_id": "runner-1",
            "lease_id": "lease-1",
            "lease_expires_at": "2099-01-01T00:05:00Z",
        },
    )
    assert lease.status_code == 200
    assert lease.json()["acquired"] is True
    assert lease.json()["state"] == "leased"

    duplicate = client.post(
        f"/internal/jobs/{job_id}/lease",
        json={
            "runner_id": "runner-2",
            "lease_id": "lease-2",
            "lease_expires_at": "2099-01-01T00:05:00Z",
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["acquired"] is False

    snapshot = client.post(
        f"/internal/jobs/{job_id}/snapshot",
        json={
            "runner_id": "runner-1",
            "state": "running",
            "result_json": {"n_total_trials": 1},
            "started_at": "2026-08-14T00:00:00Z",
        },
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["state"] == "running"
    assert snapshot.json()["result_json"] == {"n_total_trials": 1}


def test_record_and_list_artifacts() -> None:
    client, _repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]

    created = client.post(
        f"/internal/jobs/{job_id}/artifacts",
        json={
            "kind": "result",
            "storage_type": "runner-local",
            "storage_key": "jobs/job-1/result.json",
            "size_bytes": 123,
        },
    )

    assert created.status_code == 201
    assert created.json()["id"] == 1
    artifacts = client.get(f"/jobs/{job_id}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()[0]["storage_key"] == "jobs/job-1/result.json"


def test_artifact_content_proxy_is_disabled_by_default(tmp_path) -> None:
    client, _repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    artifact_file = tmp_path / "result.json"
    artifact_file.write_text("{}")
    artifact = client.post(
        f"/internal/jobs/{job_id}/artifacts",
        json={
            "kind": "result",
            "storage_type": "runner-local",
            "storage_key": str(artifact_file),
        },
    ).json()

    response = client.get(f"/jobs/{job_id}/artifacts/{artifact['id']}/content")

    assert response.status_code == 404


def test_artifact_content_proxy_serves_only_allowed_root(tmp_path) -> None:
    client, _repo, _publisher = _client(artifact_allowed_root=tmp_path)
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    artifact_file = tmp_path / "result.json"
    artifact_file.write_text('{"ok": true}')
    artifact = client.post(
        f"/internal/jobs/{job_id}/artifacts",
        json={
            "kind": "result",
            "storage_type": "runner-local",
            "storage_key": str(artifact_file),
        },
    ).json()

    response = client.get(f"/jobs/{job_id}/artifacts/{artifact['id']}/content")

    assert response.status_code == 200
    assert response.text == '{"ok": true}'


def test_artifact_content_proxy_rejects_paths_outside_allowed_root(tmp_path) -> None:
    client, _repo, _publisher = _client(artifact_allowed_root=tmp_path / "allowed")
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]
    outside_file = tmp_path / "outside.json"
    outside_file.write_text("{}")
    artifact = client.post(
        f"/internal/jobs/{job_id}/artifacts",
        json={
            "kind": "result",
            "storage_type": "runner-local",
            "storage_key": str(outside_file),
        },
    ).json()

    response = client.get(f"/jobs/{job_id}/artifacts/{artifact['id']}/content")

    assert response.status_code == 403


def test_missing_job_returns_404() -> None:
    client, _repo, _publisher = _client()

    response = client.get("/jobs/missing")

    assert response.status_code == 404


def test_snapshot_syncs_trial_results_to_trials_endpoint() -> None:
    client, _repo, _publisher = _client()
    job_id = client.post("/jobs", json={"job_config": {"job_name": "job-1"}}).json()[
        "id"
    ]

    snapshot = client.post(
        f"/internal/jobs/{job_id}/snapshot",
        json={
            "runner_id": "runner-1",
            "state": "succeeded",
            "result_json": {
                "n_total_trials": 1,
                "trial_results": [_trial_result_json()],
            },
            "started_at": "2026-08-14T00:00:00Z",
            "finished_at": "2026-08-14T00:01:00Z",
        },
    )
    assert snapshot.status_code == 200

    response = client.get(f"/jobs/{job_id}/trials")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "trial-1",
            "job_id": job_id,
            "state": "succeeded",
            "task_name": "task-a",
            "agent_name": "codex",
            "model_name": "gpt-5",
            "reward": 1.0,
            "exception_type": None,
            "result_json": _trial_result_json(),
            "started_at": "2026-08-14T00:00:00Z",
            "updated_at": response.json()[0]["updated_at"],
            "finished_at": "2026-08-14T00:01:00Z",
        }
    ]
