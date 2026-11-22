from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from azure.storage.queue import QueueClient


@dataclass(frozen=True)
class QueueMessage:
    message_id: str
    dequeue_count: int
    pop_receipt: str | None
    payload: dict[str, str]


class QueueProducer(Protocol):
    def send_product_reference(
        self,
        run_id: str,
        product_id: str,
        source_url: str,
        product_name: str | None = None,
    ) -> str: ...


class InMemoryQueue:
    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.poison_messages: list[QueueMessage] = []

    def send_product_reference(
        self,
        run_id: str,
        product_id: str,
        source_url: str,
        product_name: str | None = None,
    ) -> str:
        message_id = f"{run_id}:{product_id}"
        self.messages.append(
            QueueMessage(
                message_id=message_id,
                dequeue_count=1,
                pop_receipt=None,
                payload={
                    "run_id": run_id,
                    "product_id": product_id,
                    "source_url": source_url,
                    "product_name": product_name or product_id,
                },
            )
        )
        return message_id

    def receive(self) -> list[QueueMessage]:
        return list(self.messages)

    def delete(self, message: QueueMessage) -> None:
        self.messages = [item for item in self.messages if item.message_id != message.message_id]

    def transfer_to_poison(self, message: QueueMessage) -> None:
        self.poison_messages.append(message)
        self.delete(message)


class AzureQueueProducer:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        self.queue_name = queue_name
        self.client = QueueClient.from_connection_string(
            connection_string,
            queue_name=queue_name,
        )
        self.client.create_queue()

    def send_product_reference(
        self,
        run_id: str,
        product_id: str,
        source_url: str,
        product_name: str | None = None,
    ) -> str:
        payload = json.dumps(
            {
                "run_id": run_id,
                "product_id": product_id,
                "source_url": source_url,
                "product_name": product_name or product_id,
            },
            separators=(",", ":"),
        )
        result = self.client.send_message(payload)
        return str(result.id)


class AzureQueueConsumer:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        self.queue_name = queue_name
        self.client = QueueClient.from_connection_string(
            connection_string,
            queue_name=queue_name,
        )
        self.poison_client = QueueClient.from_connection_string(
            connection_string,
            queue_name=f"{queue_name}-poison",
        )
        self.client.create_queue()
        self.poison_client.create_queue()

    def receive(self) -> list[QueueMessage]:
        messages: list[QueueMessage] = []
        for item in self.client.receive_messages(messages_per_page=32, visibility_timeout=30):
            try:
                payload = json.loads(item.content)
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            source_url = payload.get("source_url", "")
            messages.append(
                QueueMessage(
                    message_id=str(item.id),
                    dequeue_count=int(item.dequeue_count or 0),
                    pop_receipt=item.pop_receipt,
                    payload={
                        "run_id": str(payload.get("run_id", "")),
                        "product_id": str(payload.get("product_id", "")),
                        "source_url": source_url if isinstance(source_url, str) else "",
                        "product_name": str(
                            payload.get("product_name") or payload.get("product_id") or ""
                        ),
                    },
                )
            )
        return messages

    def delete(self, message: QueueMessage) -> None:
        if message.pop_receipt:
            self.client.delete_message(message.message_id, message.pop_receipt)

    def transfer_to_poison(self, message: QueueMessage) -> None:
        payload = json.dumps(message.payload, separators=(",", ":"))
        self.poison_client.send_message(payload)
        self.delete(message)
