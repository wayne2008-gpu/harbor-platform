from typing import Protocol

from harbor_service_contracts import JobDispatchMessage


class JobPublisher(Protocol):
    def publish_job(self, message: JobDispatchMessage) -> None: ...


class InMemoryJobPublisher:
    def __init__(self) -> None:
        self.messages: list[JobDispatchMessage] = []

    def publish_job(self, message: JobDispatchMessage) -> None:
        self.messages.append(message)


class RocketMQJobPublisher:
    def __init__(self, producer, *, topic: str) -> None:
        self.producer = producer
        self.topic = topic

    def publish_job(self, message: JobDispatchMessage) -> None:
        self.producer.send_sync(
            self.topic,
            message.model_dump_json().encode("utf-8"),
            keys=message.job_id,
        )


class RocketMQSdkProducerAdapter:
    def __init__(self, producer, message_factory) -> None:
        self.producer = producer
        self.message_factory = message_factory

    def send_sync(self, topic: str, body: bytes, *, keys: str) -> None:
        message = self.message_factory(topic)
        message.set_keys(keys)
        message.set_body(body)
        self.producer.send_sync(message)


def create_rocketmq_job_publisher(
    *,
    namesrv_addr: str,
    topic: str,
    producer_group: str = "harbor-api",
) -> RocketMQJobPublisher:
    try:
        from rocketmq.client import Message, Producer
    except ImportError as exc:
        raise RuntimeError(
            "rocketmq-client-python and librocketmq are required for RocketMQ publishing"
        ) from exc

    producer = Producer(producer_group)
    producer.set_name_server_address(namesrv_addr)
    producer.start()
    return RocketMQJobPublisher(
        RocketMQSdkProducerAdapter(producer, Message),
        topic=topic,
    )
