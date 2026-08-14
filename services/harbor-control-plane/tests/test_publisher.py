from harbor_service_contracts import JobDispatchMessage

from harbor_control_plane.publisher import (
    RocketMQJobPublisher,
    RocketMQSdkProducerAdapter,
)


class FakeProducer:
    def __init__(self) -> None:
        self.calls = []

    def send_sync(self, topic: str, body: bytes, *, keys: str) -> None:
        self.calls.append((topic, body, keys))


def test_rocketmq_publisher_serializes_dispatch_message() -> None:
    producer = FakeProducer()
    message = JobDispatchMessage(message_id="msg-1", job_id="job-1")

    RocketMQJobPublisher(producer, topic="harbor_jobs").publish_job(message)

    assert len(producer.calls) == 1
    topic, body, keys = producer.calls[0]
    assert topic == "harbor_jobs"
    assert keys == "job-1"
    assert JobDispatchMessage.model_validate_json(body) == message


class FakeSdkMessage:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.keys = None
        self.body = None

    def set_keys(self, keys: str) -> None:
        self.keys = keys

    def set_body(self, body: bytes) -> None:
        self.body = body


class FakeSdkProducer:
    def __init__(self) -> None:
        self.messages = []

    def send_sync(self, message: FakeSdkMessage) -> None:
        self.messages.append(message)


def test_rocketmq_sdk_adapter_builds_sdk_message() -> None:
    producer = FakeSdkProducer()
    adapter = RocketMQSdkProducerAdapter(producer, FakeSdkMessage)

    adapter.send_sync("harbor_jobs", b"payload", keys="job-1")

    assert len(producer.messages) == 1
    assert producer.messages[0].topic == "harbor_jobs"
    assert producer.messages[0].keys == "job-1"
    assert producer.messages[0].body == b"payload"
