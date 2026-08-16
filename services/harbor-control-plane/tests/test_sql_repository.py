from datetime import UTC, datetime, timedelta

from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactQueryRequest,
    ArtifactRetryRequest,
    ArtifactState,
    InputDataset,
    InputState,
    JobBatchGetRequest,
    JobCancelRequest,
    JobClaimRequest,
    JobQueryRequest,
    JobRetryRequest,
    JobSnapshotRequest,
    JobState,
    MaterializedInputDataset,
    RunnerHeartbeatRequest,
    RunnerState,
    TrialQueryRequest,
    TrialState,
)
from sqlalchemy import func, select

from harbor_control_plane.db import create_schema, job_events_table, make_engine
from harbor_control_plane.sql_repository import SqlJobRepository


def _repo() -> SqlJobRepository:
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    return SqlJobRepository(engine)


def _trial_result_json(
    *,
    trial_id: str = "trial-1",
    exception_type: str | None = None,
    rewards: dict[str, int | float] | None = None,
) -> dict:
    result = {
        "id": trial_id,
        "task_name": "task-a",
        "trial_name": "task-a__abc1234",
        "agent_info": {
            "name": "codex",
            "version": "1",
            "model_info": {"name": "gpt-5"},
        },
        "started_at": "2026-08-14T00:00:00Z",
        "finished_at": "2026-08-14T00:01:00Z",
    }
    if rewards is not None:
        result["verifier_result"] = {"rewards": rewards}
    if exception_type is not None:
        result["exception_info"] = {"exception_type": exception_type}
    return result


def test_sql_repository_create_get_and_event() -> None:
    repo = _repo()

    record = repo.create_job(
        job_id="job-1",
        job_config={"job_name": "job-1", "environment": {"type": "ags"}},
        input_datasets=[
            InputDataset(
                name="dataset-a",
                version="v1",
                uri="cos://harbor-datasets/datasets/a.tar.gz",
                checksum_sha256="abc",
            )
        ],
        provider="ags",
    )

    assert record.state == JobState.QUEUED
    assert record.input_state == InputState.PENDING
    assert record.provider == "ags"
    assert record.input_datasets[0].name == "dataset-a"
    assert record.materialized_inputs == []
    assert repo.get_job("job-1").job_config["job_name"] == "job-1"

    with repo.engine.begin() as connection:
        count = connection.execute(
            select(func.count()).select_from(job_events_table)
        ).scalar_one()
    assert count == 1


def test_sql_repository_cancel_queued_job_moves_to_terminal_state() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    record = repo.request_cancel("job-1")

    assert record.state == JobState.CANCELLED
    assert record.cancel_requested_at is not None
    assert record.finished_at is not None


def test_sql_repository_mark_dispatch_failed_moves_to_terminal_state_and_event() -> (
    None
):
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    record = repo.mark_dispatch_failed("job-1", error_message="topic unavailable")

    assert record.state == JobState.FAILED
    assert record.error_type == "dispatch_failed"
    assert record.error_message == "topic unavailable"
    assert record.finished_at is not None
    assert repo.list_queued_job_ids(limit=10) == []
    with repo.engine.begin() as connection:
        events = connection.execute(
            select(job_events_table.c.event_type, job_events_table.c.payload_json)
            .where(job_events_table.c.job_id == "job-1")
            .order_by(job_events_table.c.id)
        ).all()
    assert events[-1].event_type == "dispatch_failed"
    assert events[-1].payload_json["previous_state"] == "queued"
    assert events[-1].payload_json["error_message"] == "topic unavailable"


def test_sql_repository_acquire_lease_is_conditional() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    assert repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=expires_at,
    )
    assert not repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-2",
        lease_id="lease-2",
        lease_expires_at=expires_at,
    )

    record = repo.get_job("job-1")
    assert record.state == JobState.LEASED
    assert record.runner_id == "runner-1"


def test_sql_repository_requeues_expired_leases_and_records_event() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    requeued = repo.requeue_expired_leases()

    assert requeued == ["job-1"]
    record = repo.get_job("job-1")
    assert record.state == JobState.QUEUED
    assert record.runner_id is None
    assert record.lease_id is None
    assert record.lease_expires_at is None
    with repo.engine.begin() as connection:
        events = connection.execute(
            select(job_events_table.c.event_type, job_events_table.c.payload_json)
            .where(job_events_table.c.job_id == "job-1")
            .order_by(job_events_table.c.id)
        ).all()
    assert events[-1].event_type == "lease_expired"
    assert events[-1].payload_json["lease_id"] == "lease-1"


def test_sql_repository_list_queued_job_ids_requeues_expired_leases() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    assert repo.list_queued_job_ids(limit=10) == ["job-1"]


def test_sql_repository_acquire_lease_reclaims_expired_lease() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    assert repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-2",
        lease_id="lease-2",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    record = repo.get_job("job-1")
    assert record.state == JobState.LEASED
    assert record.runner_id == "runner-2"
    assert record.lease_id == "lease-2"


def test_sql_repository_mark_stale_runners_offline() -> None:
    repo = _repo()
    runner = repo.heartbeat_runner(
        RunnerHeartbeatRequest(runner_id="runner-1", running_jobs=0)
    )
    assert runner.state == RunnerState.ONLINE

    marked = repo.mark_stale_runners_offline(
        stale_before=datetime.now(UTC) + timedelta(seconds=1)
    )

    assert marked == ["runner-1"]
    assert repo.list_runners()[0].state == RunnerState.OFFLINE


def test_sql_repository_does_not_lease_cancelled_job() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.request_cancel("job-1")

    assert not repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_sql_repository_lists_only_available_queued_job_ids() -> None:
    repo = _repo()
    for job_id in ["job-1", "job-2", "job-3", "job-4"]:
        repo.create_job(job_id=job_id, job_config={"job_name": job_id}, provider=None)

    repo.request_cancel("job-2")
    repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    assert repo.list_queued_job_ids(limit=1) == ["job-3"]
    assert repo.list_queued_job_ids(limit=10) == ["job-3", "job-4"]


def test_sql_repository_heartbeat_and_snapshot() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    runner = repo.heartbeat_runner(
        RunnerHeartbeatRequest(
            runner_id="runner-1",
            running_jobs=1,
            capabilities={"providers": ["docker"]},
        )
    )
    assert runner.id == "runner-1"
    assert runner.running_jobs == 1
    assert repo.list_runners()[0].capabilities == {"providers": ["docker"]}

    record = repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(
            runner_id="runner-1",
            state=JobState.RUNNING,
            result_json={"n_total_trials": 2},
        ),
    )

    assert record.state == JobState.RUNNING
    assert record.runner_id == "runner-1"
    assert record.result_json == {"n_total_trials": 2}


def test_sql_repository_records_and_lists_artifacts() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    uploaded_at = datetime(2026, 8, 16, 1, 2, 3, tzinfo=UTC)

    artifact = repo.record_artifact(
        "job-1",
        ArtifactCreateRequest(
            kind="result",
            storage_type="cos",
            storage_key="cos://bucket/dev/jobs/job-1/result.json",
            size_bytes=123,
            relative_path="result.json",
            checksum_sha256="abc",
            etag="etag-1",
            content_type="application/json",
            uploaded_at=uploaded_at,
            metadata={"bucket": "bucket", "key": "dev/jobs/job-1/result.json"},
        ),
    )

    assert artifact.id == 1
    stored = repo.list_artifacts("job-1")[0]
    assert stored.storage_key == "cos://bucket/dev/jobs/job-1/result.json"
    assert stored.relative_path == "result.json"
    assert stored.checksum_sha256 == "abc"
    assert stored.etag == "etag-1"
    assert stored.content_type == "application/json"
    assert stored.uploaded_at is not None
    assert stored.uploaded_at.replace(tzinfo=UTC) == uploaded_at
    assert stored.metadata == {
        "bucket": "bucket",
        "key": "dev/jobs/job-1/result.json",
    }


def test_sql_repository_query_and_batch_get_jobs() -> None:
    repo = _repo()
    first = repo.create_job(
        job_id="job-1",
        job_config={"job_name": "job-1", "environment": {"type": "tke"}},
        provider="tke",
        requirements={"provider": "tke"},
    )
    second = repo.create_job(
        job_id="job-2",
        job_config={"job_name": "job-2", "environment": {"type": "ags"}},
        provider="ags",
        requirements={"provider": "ags"},
    )

    page = repo.query_jobs(JobQueryRequest(states=[JobState.QUEUED], limit=1))
    next_page = repo.query_jobs(
        JobQueryRequest(states=[JobState.QUEUED], limit=1, cursor=page.next_cursor)
    )
    batch = repo.batch_get_jobs(JobBatchGetRequest(ids=["job-2", "job-1"]))

    assert page.items[0].id == first.id
    assert page.next_cursor is not None
    assert next_page.items[0].id == second.id
    assert [item.id for item in batch] == ["job-2", "job-1"]


def test_sql_repository_query_trials_and_artifacts() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(
            runner_id="runner-1",
            state=JobState.SUCCEEDED,
            result_json={"trial_results": [_trial_result_json(rewards={"reward": 1})]},
        ),
    )
    repo.record_artifact(
        "job-1",
        ArtifactCreateRequest(
            kind="trajectory",
            storage_type="cos",
            storage_key=(
                "cos://bucket/jobs/job-1/trial-1/agent/trajectory.openai-messages.json"
            ),
            trial_id="trial-1",
            relative_path="trial-1/agent/trajectory.openai-messages.json",
            content_type="application/json",
            metadata={"schema": "openai_messages"},
        ),
    )

    trials = repo.query_trials(
        TrialQueryRequest(job_id="job-1", states=[TrialState.SUCCEEDED])
    )
    artifacts = repo.query_artifacts(
        ArtifactQueryRequest(
            job_id="job-1",
            kinds=["trajectory"],
            schemas=["openai_messages"],
            content_types=["application/json"],
            relative_path_prefix="trial-1/agent/",
        )
    )

    assert trials.items[0].id == "trial-1"
    assert artifacts.items[0].kind == "trajectory"
    assert artifacts.items[0].metadata["schema"] == "openai_messages"


def test_sql_repository_cancel_control_claim_and_retry() -> None:
    repo = _repo()
    repo.create_job(
        job_id="job-1",
        job_config={"job_name": "job-1", "environment": {"type": "tke"}},
        input_datasets=[
            InputDataset(
                name="dataset-a",
                uri="cos://harbor-datasets/datasets/a.tar.gz",
            )
        ],
        provider="tke",
        requirements={"provider": "tke", "required_features": ["cos-input"]},
    )

    no_match = repo.claim_jobs(
        JobClaimRequest(
            runner_id="runner-1",
            capabilities={"providers": ["tke"], "features": []},
        )
    )
    matched = repo.claim_jobs(
        JobClaimRequest(
            runner_id="runner-1",
            capabilities={"providers": ["tke"], "features": ["cos-input"]},
        )
    )
    cancelled = repo.request_cancel(
        "job-1",
        JobCancelRequest(reason="stop", grace_period_sec=5),
    )
    control = repo.get_job_control("job-1")
    retry = repo.retry_job(
        "job-1",
        new_job_id="job-2",
        request=JobRetryRequest(reason="rerun"),
    )
    artifact_retry = repo.request_artifact_retry(
        "job-1",
        ArtifactRetryRequest(reason="retry upload"),
    )

    assert no_match.claimed == []
    assert matched.claimed[0].job_id == "job-1"
    assert cancelled.state == JobState.CANCELLING
    assert control.cancel_requested is True
    assert control.cancel_grace_period_sec == 5
    assert retry.parent_job_id == "job-1"
    assert retry.root_job_id == "job-1"
    assert retry.attempt == 2
    assert artifact_retry.artifact_state == ArtifactState.PENDING
    assert artifact_retry.error_message == "retry upload"


def test_sql_repository_claims_artifact_retry_for_original_runner() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.acquire_lease(
        job_id="job-1",
        runner_id="runner-1",
        lease_id="lease-1",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(runner_id="runner-1", state=JobState.SUCCEEDED),
    )
    repo.update_artifact_state(
        "job-1",
        artifact_state=ArtifactState.PARTIAL_FAILED,
        error_message="cos timeout",
    )
    repo.request_artifact_retry("job-1", ArtifactRetryRequest(reason="retry upload"))

    wrong_runner = repo.claim_jobs(JobClaimRequest(runner_id="runner-2"))
    claimed = repo.claim_jobs(JobClaimRequest(runner_id="runner-1"))

    assert wrong_runner.claimed == []
    assert claimed.claimed[0].job_id == "job-1"
    assert claimed.claimed[0].action == "artifact-retry"
    assert claimed.claimed[0].job.artifact_state == ArtifactState.UPLOADING


def test_sql_repository_updates_artifact_state_and_records_event() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    record = repo.update_artifact_state(
        "job-1",
        artifact_state=ArtifactState.PARTIAL_FAILED,
        error_message="cos timeout",
    )

    assert record.state == JobState.QUEUED
    assert record.artifact_state == ArtifactState.PARTIAL_FAILED
    assert record.error_message == "cos timeout"
    with repo.engine.begin() as connection:
        events = connection.execute(
            select(job_events_table.c.event_type, job_events_table.c.payload_json)
            .where(job_events_table.c.job_id == "job-1")
            .order_by(job_events_table.c.id)
        ).all()
    assert events[-1].event_type == "artifact_state"
    assert events[-1].payload_json == {
        "artifact_state": "partial_failed",
        "error_message": "cos timeout",
    }


def test_sql_repository_updates_input_state_and_records_event() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    record = repo.update_input_state(
        "job-1",
        input_state=InputState.SUCCEEDED,
        materialized_inputs=[
            MaterializedInputDataset(
                name="dataset-a",
                source_type="cos",
                uri="cos://harbor-datasets/datasets/a.tar.gz",
                format="tar.gz",
                checksum_sha256="abc",
                target="dataset-a",
                local_path="inputs/datasets/dataset-a",
                size_bytes=123,
                state=InputState.SUCCEEDED,
            )
        ],
    )

    assert record.state == JobState.QUEUED
    assert record.input_state == InputState.SUCCEEDED
    assert record.materialized_inputs[0].local_path == "inputs/datasets/dataset-a"
    with repo.engine.begin() as connection:
        events = connection.execute(
            select(job_events_table.c.event_type, job_events_table.c.payload_json)
            .where(job_events_table.c.job_id == "job-1")
            .order_by(job_events_table.c.id)
        ).all()
    assert events[-1].event_type == "input_state"
    assert events[-1].payload_json == {
        "input_state": "succeeded",
        "error_message": None,
    }


def test_sql_repository_marks_input_materialization_failed() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    record = repo.mark_input_materialization_failed(
        "job-1",
        error_message="checksum mismatch",
    )

    assert record.state == JobState.FAILED
    assert record.input_state == InputState.FAILED
    assert record.error_type == "input_materialization_failed"
    assert record.error_message == "checksum mismatch"
    assert record.finished_at is not None


def test_sql_repository_snapshot_syncs_trial_results() -> None:
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)

    repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(
            runner_id="runner-1",
            state=JobState.SUCCEEDED,
            result_json={
                "n_total_trials": 2,
                "trial_results": [
                    _trial_result_json(rewards={"reward": 1}),
                    _trial_result_json(
                        trial_id="trial-2", exception_type="RuntimeError"
                    ),
                ],
            },
        ),
    )

    trials = repo.list_trials("job-1")

    assert [trial.id for trial in trials] == ["trial-1", "trial-2"]
    assert trials[0].state == TrialState.SUCCEEDED
    assert trials[0].task_name == "task-a"
    assert trials[0].agent_name == "codex"
    assert trials[0].model_name == "gpt-5"
    assert trials[0].reward == 1.0
    assert trials[1].state == TrialState.FAILED
    assert trials[1].exception_type == "RuntimeError"


def test_sql_repository_snapshot_without_trial_results_preserves_existing_trials() -> (
    None
):
    repo = _repo()
    repo.create_job(job_id="job-1", job_config={"job_name": "job-1"}, provider=None)
    repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(
            runner_id="runner-1",
            state=JobState.RUNNING,
            result_json={"trial_results": [_trial_result_json(rewards={"reward": 1})]},
            started_at=datetime(2026, 8, 14, tzinfo=UTC),
        ),
    )

    repo.apply_snapshot(
        "job-1",
        JobSnapshotRequest(
            runner_id="runner-1",
            state=JobState.RUNNING,
            result_json={"n_total_trials": 1},
        ),
    )

    record = repo.get_job("job-1")
    assert record.started_at is not None
    assert record.started_at.replace(tzinfo=UTC) == datetime(2026, 8, 14, tzinfo=UTC)
    assert [trial.id for trial in repo.list_trials("job-1")] == ["trial-1"]
