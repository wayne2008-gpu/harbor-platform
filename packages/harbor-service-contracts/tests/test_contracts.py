from datetime import UTC, datetime

from harbor_service_contracts import (
    ArtifactCreateRequest,
    ArtifactQueryRequest,
    ArtifactRetryRequest,
    ArtifactState,
    InputDataset,
    InputState,
    InputStateUpdateRequest,
    JobCancelRequest,
    JobClaimRequest,
    JobCreateRequest,
    JobDispatchMessage,
    JobDispatchRouting,
    JobQueryRequest,
    JobRetryRequest,
    JobState,
    MaterializedInputDataset,
    is_valid_job_transition,
)


def test_job_state_transitions_cover_mvp_lifecycle() -> None:
    assert is_valid_job_transition(JobState.QUEUED, JobState.LEASED)
    assert is_valid_job_transition(JobState.LEASED, JobState.RUNNING)
    assert is_valid_job_transition(JobState.RUNNING, JobState.CANCELLING)
    assert is_valid_job_transition(JobState.CANCELLING, JobState.CANCELLED)
    assert is_valid_job_transition(JobState.RUNNING, JobState.SUCCEEDED)
    assert is_valid_job_transition(JobState.RUNNING, JobState.FAILED)
    assert is_valid_job_transition(JobState.RUNNING, JobState.CANCELLED)
    assert not is_valid_job_transition(JobState.SUCCEEDED, JobState.RUNNING)


def test_job_dispatch_message_round_trips_json() -> None:
    message = JobDispatchMessage(
        message_id="msg-1",
        job_id="job-1",
        created_at=datetime.now(UTC),
        routing=JobDispatchRouting(provider="ags", tags=["gpu"]),
    )

    restored = JobDispatchMessage.model_validate_json(message.model_dump_json())

    assert restored == message
    assert restored.schema_version == 1


def test_artifact_contract_carries_storage_metadata() -> None:
    request = ArtifactCreateRequest(
        kind="trajectory",
        storage_type="cos",
        storage_key="cos://bucket/prefix/jobs/job-1/trial-a/agent/trajectory.json",
        trial_id="trial-a",
        size_bytes=123,
        relative_path="trial-a/agent/trajectory.json",
        checksum_sha256="abc",
        etag="etag-1",
        content_type="application/json",
        metadata={"source": "runner"},
    )

    assert request.storage_type == "cos"
    assert request.relative_path == "trial-a/agent/trajectory.json"
    assert request.metadata == {"source": "runner"}
    assert ArtifactState.PENDING == "pending"


def test_job_create_contract_carries_input_datasets() -> None:
    request = JobCreateRequest(
        job_config={"job_name": "job-1"},
        input_datasets=[
            InputDataset(
                name="dataset-a",
                version="v1",
                uri="cos://bucket/datasets/dataset-a/v1/dataset.tar.gz",
                checksum_sha256="abc",
            )
        ],
    )

    assert request.input_datasets[0].source_type == "cos"
    assert request.input_datasets[0].format == "tar.gz"


def test_input_state_update_contract_round_trips() -> None:
    update = InputStateUpdateRequest(
        input_state=InputState.SUCCEEDED,
        materialized_inputs=[
            MaterializedInputDataset(
                name="dataset-a",
                source_type="cos",
                uri="cos://bucket/datasets/dataset-a/v1/dataset.tar.gz",
                format="tar.gz",
                checksum_sha256="abc",
                target="dataset-a",
                local_path="inputs/datasets/dataset-a",
                size_bytes=123,
                state=InputState.SUCCEEDED,
            )
        ],
    )

    restored = InputStateUpdateRequest.model_validate_json(update.model_dump_json())

    assert restored == update
    assert restored.materialized_inputs[0].state == InputState.SUCCEEDED


def test_query_cancel_claim_and_retry_contracts_round_trip() -> None:
    job_query = JobQueryRequest(
        states=[JobState.QUEUED],
        provider="tke",
        limit=25,
    )
    artifact_query = ArtifactQueryRequest(kinds=["trajectory"], storage_types=["cos"])
    cancel = JobCancelRequest(reason="bad prompt", grace_period_sec=3)
    claim = JobClaimRequest(
        runner_id="runner-1",
        max_jobs=2,
        capabilities={"providers": ["tke"], "features": ["cos-input"]},
    )
    job_retry = JobRetryRequest(reason="rerun with same inputs")
    artifact_retry = ArtifactRetryRequest(reason="upload failed")

    assert JobQueryRequest.model_validate_json(job_query.model_dump_json()) == job_query
    assert artifact_query.kinds == ["trajectory"]
    assert cancel.mode == "graceful"
    assert claim.capabilities["features"] == ["cos-input"]
    assert job_retry.reason == "rerun with same inputs"
    assert artifact_retry.reason == "upload failed"
