from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class SyntheticTaskState(StrEnum):
    SUBMITTED = "submitted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PUBLISHED = "published"


@dataclass
class SyntheticTaskRecord:
    id: str
    name: str
    harbor_job_id: str
    state: SyntheticTaskState
    created_at: datetime
    updated_at: datetime
    harbor_state: str | None = None
    samples: list[dict] = field(default_factory=list)


class InMemorySyntheticTaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, SyntheticTaskRecord] = {}

    def create(
        self,
        *,
        task_id: str,
        name: str,
        harbor_job_id: str,
    ) -> SyntheticTaskRecord:
        record = SyntheticTaskRecord(
            id=task_id,
            name=name,
            harbor_job_id=harbor_job_id,
            state=SyntheticTaskState.SUBMITTED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.tasks[task_id] = record
        return record

    def get(self, task_id: str) -> SyntheticTaskRecord:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise ValueError(task_id) from exc

    def sync_harbor_state(
        self, task_id: str, *, harbor_state: str
    ) -> SyntheticTaskRecord:
        record = self.get(task_id)
        record.harbor_state = harbor_state
        record.state = _synthetic_state_from_harbor_state(harbor_state)
        record.updated_at = datetime.now(UTC)
        return record

    def publish(self, task_id: str) -> SyntheticTaskRecord:
        record = self.get(task_id)
        record.state = SyntheticTaskState.PUBLISHED
        record.updated_at = datetime.now(UTC)
        return record

    def add_samples(self, task_id: str, samples: list[dict]) -> SyntheticTaskRecord:
        record = self.get(task_id)
        record.samples.extend(samples)
        record.updated_at = datetime.now(UTC)
        return record


def _synthetic_state_from_harbor_state(harbor_state: str) -> SyntheticTaskState:
    if harbor_state in {"queued", "leased"}:
        return SyntheticTaskState.SUBMITTED
    if harbor_state == "running":
        return SyntheticTaskState.RUNNING
    if harbor_state == "succeeded":
        return SyntheticTaskState.SUCCEEDED
    if harbor_state == "cancelled":
        return SyntheticTaskState.CANCELLED
    if harbor_state in {"failed", "timed_out"}:
        return SyntheticTaskState.FAILED
    return SyntheticTaskState.SUBMITTED
