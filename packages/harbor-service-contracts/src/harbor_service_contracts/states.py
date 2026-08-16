from enum import StrEnum


class JobState(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class TrialState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunnerState(StrEnum):
    ONLINE = "online"
    DRAINING = "draining"
    OFFLINE = "offline"


class LeaseState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"


class ArtifactState(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCEEDED = "succeeded"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"


class InputState(StrEnum):
    PENDING = "pending"
    MATERIALIZING = "materializing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.TIMED_OUT,
    }
)

ALLOWED_JOB_TRANSITIONS = {
    JobState.QUEUED: frozenset({JobState.LEASED, JobState.CANCELLED}),
    JobState.LEASED: frozenset({JobState.RUNNING, JobState.QUEUED, JobState.FAILED}),
    JobState.RUNNING: frozenset(
        {
            JobState.SUCCEEDED,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.TIMED_OUT,
        }
    ),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
    JobState.TIMED_OUT: frozenset(),
}


def is_valid_job_transition(current: JobState, next_state: JobState) -> bool:
    return next_state in ALLOWED_JOB_TRANSITIONS[current]
