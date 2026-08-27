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


def test_read_drops_an_undecodable_message_instead_of_raising(bus):
    # A hand-written XADD with flat fields (no JSON "data") killed the live
    # llm-worker on 2026-08-27: decoding happens inside read(), before the
    # worker loop reaches any per-message handling, so the process died on
    # read and died again on every restart because the entry stayed queued.
    bus.ensure_group("s", "g")
    bus._r.xadd("s", {"hotspot_id": "10209"})
    good = bus.publish("s", {"hotspot_id": 7})

    out = bus.read("s", "g", "c")

    assert out == [(good, {"hotspot_id": 7})], "the good message must survive"


def test_an_undecodable_message_is_acked_so_it_cannot_come_back(bus):
    bus.ensure_group("s", "g")
    bus._r.xadd("s", {"hotspot_id": "10209"})

    bus.read("s", "g", "c")

    assert bus.pending_count("s", "g") == 0, (
        "an unparseable message left pending would be reclaimed by claim_stale forever"
    )


def test_data_that_is_not_json_is_dropped_not_raised(bus):
    bus.ensure_group("s", "g")
    bus._r.xadd("s", {"data": "{not json"})
    good = bus.publish("s", {"hotspot_id": 7})

    assert bus.read("s", "g", "c") == [(good, {"hotspot_id": 7})]


def test_claim_stale_also_survives_an_undecodable_message(bus):
    bus.ensure_group("s", "g")
    bus._r.xadd("s", {"hotspot_id": "10209"})
    bus.publish("s", {"hotspot_id": 7})
    # Deliver both to consumer "c" without acking, so they sit pending.
    bus._r.xreadgroup("g", "c", {"s": ">"}, count=10)

    out = bus.claim_stale("s", "g", "c2", min_idle_ms=0)

    assert [payload for _mid, payload in out] == [{"hotspot_id": 7}]
