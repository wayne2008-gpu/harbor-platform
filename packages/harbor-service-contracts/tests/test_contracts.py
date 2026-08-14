from datetime import datetime, timezone

from harbor_service_contracts import (
    JobDispatchMessage,
    JobDispatchRouting,
    JobState,
    is_valid_job_transition,
)


def test_job_state_transitions_cover_mvp_lifecycle() -> None:
    assert is_valid_job_transition(JobState.QUEUED, JobState.LEASED)
    assert is_valid_job_transition(JobState.LEASED, JobState.RUNNING)
    assert is_valid_job_transition(JobState.RUNNING, JobState.SUCCEEDED)
    assert is_valid_job_transition(JobState.RUNNING, JobState.FAILED)
    assert is_valid_job_transition(JobState.RUNNING, JobState.CANCELLED)
    assert not is_valid_job_transition(JobState.SUCCEEDED, JobState.RUNNING)


def test_job_dispatch_message_round_trips_json() -> None:
    message = JobDispatchMessage(
        message_id="msg-1",
        job_id="job-1",
        created_at=datetime.now(timezone.utc),
        routing=JobDispatchRouting(provider="ags", tags=["gpu"]),
    )

    restored = JobDispatchMessage.model_validate_json(message.model_dump_json())

    assert restored == message
    assert restored.schema_version == 1
