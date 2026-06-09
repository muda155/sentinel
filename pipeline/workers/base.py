"""Base worker: read a consumer-group batch, handle each message, publish
results, ack on success. Failures are logged and left pending for stale-claim
replay (NFR-3). Subclasses set in_stream/group/out_stream and implement handle()."""

from __future__ import annotations

import logging
import os
import signal
import socket
import time

from pipeline.streams import StreamBus

logger = logging.getLogger(__name__)


class Worker:
    in_stream: str = ""
    group: str = ""
    out_stream: str | None = None

    def __init__(self, bus: StreamBus | None = None, consumer: str | None = None) -> None:
        self.bus = bus or StreamBus()
        self.consumer = consumer or os.getenv("HOSTNAME") or socket.gethostname()
        self._stop = False

    def setup(self) -> None:
        self.bus.ensure_group(self.in_stream, self.group)

    def handle(self, msg_id: str, data: dict) -> list[dict]:
        """Process one message. Return a list of payloads to publish to out_stream.
        Must be idempotent (safe to replay). Raise to leave the message pending."""
        raise NotImplementedError

    def _process(self, msg_id: str, data: dict) -> bool:
        try:
            results = self.handle(msg_id, data) or []
            if self.out_stream:
                for payload in results:
                    self.bus.publish(self.out_stream, payload)
            self.bus.ack(self.in_stream, self.group, msg_id)
            return True
        except Exception:
            logger.exception(
                "worker handler failed; leaving message pending",
                extra={"worker": self.group, "msg_id": msg_id},
            )
            return False

    def run_once(self) -> int:
        """One read+process cycle. Returns count of successfully processed msgs."""
        done = 0
        for msg_id, data in self.bus.read(self.in_stream, self.group, self.consumer):
            if self._process(msg_id, data):
                done += 1
        return done

    def claim_once(self) -> int:
        """Reclaim and reprocess stale (crashed-mid-flight) messages — NFR-3 replay."""
        done = 0
        for msg_id, data in self.bus.claim_stale(self.in_stream, self.group, self.consumer):
            if self._process(msg_id, data):
                done += 1
        return done

    def run_forever(self) -> None:  # pragma: no cover - exercised in integration
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "_stop", True))
        self.setup()
        logger.info("worker started", extra={"worker": self.group, "consumer": self.consumer})
        last_claim = 0.0
        while not self._stop:
            self.run_once()
            if time.monotonic() - last_claim > 60:   # sweep stragglers each minute
                self.claim_once()
                last_claim = time.monotonic()
