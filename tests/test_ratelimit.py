import time

from api.ratelimit import TokenBucket


def test_bucket_allows_then_blocks():
    b = TokenBucket(rate_per_min=2)
    assert b.allow("client-a")
    assert b.allow("client-a")
    assert not b.allow("client-a")          # 3rd within the window -> blocked
    assert b.allow("client-b")              # independent client


def test_bucket_refills_over_time():
    b = TokenBucket(rate_per_min=60)         # 1 token/sec
    assert b.allow("c")
    for _ in range(59):
        b.allow("c")
    assert not b.allow("c")
    time.sleep(1.1)
    assert b.allow("c")
