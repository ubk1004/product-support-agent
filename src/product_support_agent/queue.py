from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Protocol

from azure.core.exceptions import HttpResponseError, ResourceExistsError
from azure.storage.queue import QueueClient

# Product ingestion can take several minutes, so a received message stays invisible this long
# before another consumer may take it. A crashed consumer's message reappears after this.
DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 900


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


class ProductQueueConsumer(Protocol):
    """Takes one product at a time. At-least-once: delete a message only after it is recorded."""

    def receive_one(self) -> QueueMessage | None: ...

    def delete(self, message: QueueMessage) -> None: ...

    def transfer_to_poison(self, message: QueueMessage) -> None: ...

    def defer(self, message: QueueMessage, delay_seconds: int) -> None: ...

    def approximate_count(self) -> int: ...


def _payload(
    run_id: str, product_id: str, source_url: str, product_name: str | None
) -> dict[str, str]:
    return {
        "run_id": run_id,
        "product_id": product_id,
        "source_url": source_url,
        "product_name": product_name or product_id,
    }


def _ensure_queue(client: QueueClient) -> None:
    """Create the queue if missing (Azurite). In Azure the queues are provisioned by Bicep and
    the workload identity has data-plane roles only, so a refused create is not an error."""
    try:
        client.create_queue()
    except ResourceExistsError:
        pass
    except HttpResponseError as error:
        if error.status_code != 403:
            raise


class InMemoryQueue:
    """Process-local queue for tests. Messages in flight are hidden until deleted or released."""

    def __init__(self) -> None:
        self.messages: list[QueueMessage] = []
        self.poison_messages: list[QueueMessage] = []
        self._in_flight: set[str] = set()
        self._delayed: set[str] = set()

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
                payload=_payload(run_id, product_id, source_url, product_name),
            )
        )
        return message_id

    def receive(self) -> list[QueueMessage]:
        return list(self.messages)

    def receive_one(self) -> QueueMessage | None:
        for index, message in enumerate(self.messages):
            if message.message_id not in self._in_flight:
                received = replace(message, dequeue_count=message.dequeue_count + 1)
                self.messages[index] = received
                self._in_flight.add(received.message_id)
                return received
        return None

    def release(self, message: QueueMessage) -> None:
        """Make an unfinished message visible again, as the visibility timeout would."""
        self._in_flight.discard(message.message_id)

    def delete(self, message: QueueMessage) -> None:
        self._in_flight.discard(message.message_id)
        self.messages = [item for item in self.messages if item.message_id != message.message_id]

    def transfer_to_poison(self, message: QueueMessage) -> None:
        self.poison_messages.append(message)
        self.delete(message)

    def defer(self, message: QueueMessage, delay_seconds: int) -> None:
        """Requeue with a fresh delivery count, hidden until `make_delayed_visible`."""
        self.delete(message)
        self.messages.append(replace(message, dequeue_count=1))
        self._delayed.add(message.message_id)
        self._in_flight.add(message.message_id)

    def make_delayed_visible(self) -> None:
        """Stand-in for the delay passing: deferred messages become receivable again."""
        self._in_flight -= self._delayed
        self._delayed.clear()

    def approximate_count(self) -> int:
        return len(self.messages)


class AzureQueueProducer:
    def __init__(
        self,
        connection_string: str | None,
        queue_name: str,
        *,
        client: QueueClient | None = None,
    ) -> None:
        self.queue_name = queue_name
        self.client = client or QueueClient.from_connection_string(
            connection_string or "",
            queue_name=queue_name,
        )
        _ensure_queue(self.client)

    def send_product_reference(
        self,
        run_id: str,
        product_id: str,
        source_url: str,
        product_name: str | None = None,
    ) -> str:
        payload = json.dumps(
            _payload(run_id, product_id, source_url, product_name),
            separators=(",", ":"),
        )
        result = self.client.send_message(payload)
        return str(result.id)


class AzureQueueConsumer:
    def __init__(
        self,
        connection_string: str | None,
        queue_name: str,
        *,
        client: QueueClient | None = None,
        poison_client: QueueClient | None = None,
        visibility_timeout_seconds: int = DEFAULT_VISIBILITY_TIMEOUT_SECONDS,
    ) -> None:
        self.queue_name = queue_name
        self.visibility_timeout_seconds = visibility_timeout_seconds
        self.client = client or QueueClient.from_connection_string(
            connection_string or "",
            queue_name=queue_name,
        )
        self.poison_client = poison_client or QueueClient.from_connection_string(
            connection_string or "",
            queue_name=f"{queue_name}-poison",
        )
        _ensure_queue(self.client)
        _ensure_queue(self.poison_client)

    def receive(self) -> list[QueueMessage]:
        """Take up to a page of messages. Prefer `receive_one` for ingestion."""
        return [
            self._to_message(item)
            for item in self.client.receive_messages(messages_per_page=32, visibility_timeout=30)
        ]

    def receive_one(self) -> QueueMessage | None:
        for item in self.client.receive_messages(
            messages_per_page=1,
            max_messages=1,
            visibility_timeout=self.visibility_timeout_seconds,
        ):
            return self._to_message(item)
        return None

    @staticmethod
    def _to_message(item: object) -> QueueMessage:
        content = getattr(item, "content", "")
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        source_url = payload.get("source_url", "")
        return QueueMessage(
            message_id=str(getattr(item, "id", "")),
            dequeue_count=int(getattr(item, "dequeue_count", 0) or 0),
            pop_receipt=getattr(item, "pop_receipt", None),
            payload={
                "run_id": str(payload.get("run_id", "")),
                "product_id": str(payload.get("product_id", "")),
                "source_url": source_url if isinstance(source_url, str) else "",
                "product_name": str(payload.get("product_name") or payload.get("product_id") or ""),
            },
        )

    def delete(self, message: QueueMessage) -> None:
        if message.pop_receipt:
            self.client.delete_message(message.message_id, message.pop_receipt)

    def transfer_to_poison(self, message: QueueMessage) -> None:
        payload = json.dumps(message.payload, separators=(",", ":"))
        self.poison_client.send_message(payload)
        self.delete(message)

    def defer(self, message: QueueMessage, delay_seconds: int) -> None:
        """Put the product back as a fresh message that becomes visible after a delay.

        A fresh message restarts the delivery count, so waiting for a request budget or a
        rate-limit window is never mistaken for a poison message.
        """
        payload = json.dumps(message.payload, separators=(",", ":"))
        self.client.send_message(payload, visibility_timeout=delay_seconds)
        self.delete(message)

    def approximate_count(self) -> int:
        properties = self.client.get_queue_properties()
        return int(properties.approximate_message_count or 0)
