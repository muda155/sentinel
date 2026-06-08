import fakeredis
from pipeline.streams import StreamBus
from pipeline.workers.base import Worker


def _bus():
    return StreamBus(client=fakeredis.FakeStrictRedis(), block_ms=10, batch=10)


def test_worker_processes_acks_and_republishes():
    bus = _bus()
    seen = []

    class Doubler(Worker):
        in_stream = "in"
        group = "cg:doubler"
        out_stream = "out"

        def handle(self, msg_id, data):
            seen.append(data["n"])
            return [{"n": data["n"] * 2}]   # one outbound message

    w = Doubler(bus=bus, consumer="c1")
    w.setup()
    bus.publish("in", {"n": 21})

    processed = w.run_once()                 # read→handle→publish→ack one batch
    assert processed == 1
    assert seen == [21]
    assert bus.pending_count("in", "cg:doubler") == 0      # acked

    bus.ensure_group("out", "cg:reader")
    out_msgs = bus.read("out", "cg:reader", "r1")
    assert out_msgs[0][1] == {"n": 42}                     # republished


def test_handler_exception_leaves_message_pending():
    bus = _bus()

    class Boom(Worker):
        in_stream = "in"
        group = "cg:boom"
        out_stream = None

        def handle(self, msg_id, data):
            raise RuntimeError("kaboom")

    w = Boom(bus=bus, consumer="c1")
    w.setup()
    bus.publish("in", {"n": 1})
    processed = w.run_once()                  # swallows error, does NOT ack
    assert processed == 0
    assert bus.pending_count("in", "cg:boom") == 1
