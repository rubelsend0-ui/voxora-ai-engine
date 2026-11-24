import pytest

from app.core.errors import RateLimited
from app.core.rate_limit import InMemoryRateLimiter
from app.core.security import generate_api_key, hash_api_key


def test_api_key_hash_is_keyed_and_stable():
    raw, prefix = generate_api_key()
    assert raw.startswith("vx_") and raw.startswith(prefix)
    assert hash_api_key(raw, "pepper-a") == hash_api_key(raw, "pepper-a")
    assert hash_api_key(raw, "pepper-a") != hash_api_key(raw, "pepper-b")
    assert raw not in hash_api_key(raw, "pepper-a")


def test_keys_are_unique():
    assert generate_api_key()[0] != generate_api_key()[0]


def test_rate_limiter_blocks_then_recovers():
    now = [1000.0]
    rl = InMemoryRateLimiter(clock=lambda: now[0])
    for _ in range(3):
        rl.hit("k", 3, 60)
    with pytest.raises(RateLimited) as ei:
        rl.hit("k", 3, 60)
    assert int(ei.value.headers["Retry-After"]) >= 1
    rl.hit("other", 3, 60)  # separate bucket
    now[0] += 61
    rl.hit("k", 3, 60)  # window passed
