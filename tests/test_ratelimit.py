# Silent failure: a limiter that counts forever (visitors locked out) or never expires keys
# (memory grows with every address), or reports a Retry-After of zero while blocking.
from __future__ import annotations

from ask_hana.ratelimit import RateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_blocks_after_limit_with_retry_after_and_recovers():
    clock = Clock()
    rl = RateLimiter(2, 60, clock)
    assert rl.check("a") == (True, 0)
    clock.now += 10
    assert rl.check("a") == (True, 0)
    allowed, retry = rl.check("a")
    assert allowed is False and retry == 50
    clock.now += 51
    assert rl.check("a") == (True, 0)


def test_keys_are_independent():
    rl = RateLimiter(1, 60, Clock())
    assert rl.check("a")[0] and rl.check("b")[0]
    assert not rl.check("a")[0]


def test_stale_keys_are_pruned():
    clock = Clock()
    rl = RateLimiter(1, 60, clock, max_keys=3)
    for k in "abcd":
        rl.check(k)
    clock.now += 120
    rl.check("e")
    assert len(rl._hits) <= 2
