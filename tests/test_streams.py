import json
import fakeredis
import pytest
from pipeline.streams import StreamBus


@pytest.fixture
def bus():
    client = fakeredis.FakeStrictRedis()
    return StreamBus(client=client, block_ms=10, batch=10)


def test_publish_then_read_group_returns_payload(bus):
    bus.ensure_group("sentinel:ingested_events", "cg:gridcell")
    msg_id = bus.publish("sentinel:ingested_events", {"batch_id": "b1", "event_ids": [1, 2]})
    assert msg_id

    msgs = bus.read("sentinel:ingested_events", "cg:gridcell", "c1")
    assert len(msgs) == 1
    mid, data = msgs[0]
    assert data["batch_id"] == "b1"
    assert data["event_ids"] == [1, 2]


def test_ack_removes_from_pending(bus):
    bus.ensure_group("s", "cg")
    bus.publish("s", {"x": 1})
    msgs = bus.read("s", "cg", "c1")
    mid, _ = msgs[0]
    assert bus.pending_count("s", "cg") == 1
    bus.ack("s", "cg", mid)
    assert bus.pending_count("s", "cg") == 0


def test_claim_stale_returns_unacked_after_threshold(bus):
    bus.ensure_group("s", "cg")
    bus.publish("s", {"x": 1})
    bus.read("s", "cg", "dead-consumer")          # delivered, never acked
    claimed = bus.claim_stale("s", "cg", "c2", min_idle_ms=0)
    assert len(claimed) == 1
    assert claimed[0][1]["x"] == 1
