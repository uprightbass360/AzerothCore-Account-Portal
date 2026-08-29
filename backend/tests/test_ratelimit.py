from app.core.ratelimit import RateLimiter


def test_burst_then_deny():
    rl = RateLimiter(rate=1.0, capacity=3)
    assert [rl.allow("k", now=0.0) for _ in range(3)] == [True, True, True]
    assert rl.allow("k", now=0.0) is False


def test_refill_over_time():
    rl = RateLimiter(rate=1.0, capacity=2)
    assert rl.allow("k", now=0.0) and rl.allow("k", now=0.0)
    assert rl.allow("k", now=0.5) is False
    assert rl.allow("k", now=1.1) is True


def test_keys_independent():
    rl = RateLimiter(rate=1.0, capacity=1)
    assert rl.allow("a", now=0.0) is True
    assert rl.allow("b", now=0.0) is True
    assert rl.allow("a", now=0.0) is False


def test_capacity_not_exceeded_by_long_idle():
    rl = RateLimiter(rate=1.0, capacity=2)
    rl.allow("k", now=0.0)
    assert [rl.allow("k", now=1000.0) for _ in range(3)] == [True, True, False]


def test_now_defaults_to_monotonic():
    rl = RateLimiter(rate=1000.0, capacity=1)
    assert rl.allow("k") is True
