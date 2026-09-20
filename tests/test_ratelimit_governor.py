from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import time

import pytest

from rate_limit_governor import (
    AdaptiveRateLimiter, BackoffStrategy, CircuitBreaker, CircuitState,
    ExponentialBackoff, JitterStrategy, RateLimitBackoffGovernor,
    RateLimitHeaderParser, RetryBudgetManager, SlidingWindowRateLimiter,
    TokenBucket,
)


def test_token_bucket_capacity_and_validation():
    bucket = TokenBucket(2, 0)
    assert bucket.consume()
    assert bucket.consume()
    assert not bucket.consume()
    assert bucket.time_until_tokens() == float("inf")
    with pytest.raises(ValueError):
        TokenBucket(0, 1)
    with pytest.raises(ValueError):
        bucket.consume(0)


def test_sliding_window_expires_and_undoes():
    limiter = SlidingWindowRateLimiter(0.02, 1)
    assert limiter.allow()
    assert not limiter.allow()
    limiter.undo_last()
    assert limiter.allow()
    limiter.reset()
    assert limiter.remaining == 1


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (BackoffStrategy.EXPONENTIAL, [1.0, 2.0, 4.0]),
        (BackoffStrategy.LINEAR, [1.0, 2.0, 3.0]),
        (BackoffStrategy.FIBONACCI, [1.0, 2.0, 3.0]),
    ],
)
def test_backoff_schedules(strategy, expected):
    backoff = ExponentialBackoff(1, 100, strategy, JitterStrategy.NONE)
    assert [backoff.calculate_delay(i) for i in range(3)] == expected


def test_decorrelated_jitter_is_capped():
    backoff = ExponentialBackoff(10, 40, jitter=JitterStrategy.DECORRELATED)
    assert all(10 <= backoff.calculate_delay(8, previous_delay=40) <= 40 for _ in range(50))


def test_backoff_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        ExponentialBackoff(-1, 10)
    with pytest.raises(ValueError):
        ExponentialBackoff(10, 5)


def test_circuit_breaker_cycle_and_probe_bound():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0, half_open_max=2)
    breaker.record_failure()
    assert breaker.state == CircuitState.HALF_OPEN
    assert breaker.allow_request()
    assert breaker.allow_request()
    assert not breaker.allow_request()
    breaker.record_success()
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_circuit_reset_closes_open_breaker():
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=100)
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    breaker.reset()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.allow_request()


def test_retry_budget_is_enforced_atomically():
    budget = RetryBudgetManager(max_retries=2, window_sec=1)
    assert budget.record_retry()
    assert budget.record_retry()
    assert not budget.record_retry()
    assert budget.remaining == 0


def test_retry_after_seconds_and_http_date():
    seconds = RateLimitHeaderParser.parse({"Retry-After": "30"})
    assert seconds.retry_after == 30
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    parsed = RateLimitHeaderParser.parse({"Retry-After": format_datetime(future, usegmt=True)})
    assert parsed.retry_after is not None
    assert 20 <= parsed.retry_after <= 30


def test_header_parser_ignores_invalid_values():
    parsed = RateLimitHeaderParser.parse({"X-RateLimit-Limit": "bad", "Retry-After": "not-a-date"})
    assert parsed.limit is None
    assert parsed.retry_after is None


def test_adaptive_limiter_tracks_requests_separately():
    limiter = AdaptiveRateLimiter(base_limit=2, window_sec=1)
    assert limiter.is_allowed()
    limiter.record_request()
    limiter.record_request()
    assert not limiter.is_allowed()


def test_adaptive_limiter_reduces_on_429_and_recovers_slowly():
    limiter = AdaptiveRateLimiter(base_limit=100)
    limiter.record_response(429)
    assert limiter.current_limit == 50
    for _ in range(20):
        limiter.record_response(200)
    assert limiter.current_limit == 51


def test_governor_allows_and_reports_status():
    governor = RateLimitBackoffGovernor(capacity=2, refill_rate=0, max_requests=10)
    decision = governor.check_request("api")
    assert decision.allowed
    status = governor.get_status()
    assert status["token_bucket"]["capacity"] == 2
    assert status["active_backoffs"] == 0


def test_governor_sliding_window_rejection_refunds_token():
    governor = RateLimitBackoffGovernor(capacity=2, refill_rate=0, window_sec=60, max_requests=1)
    assert governor.check_request("api").allowed
    before = governor.token_bucket.available
    rejected = governor.check_request("api")
    assert not rejected.allowed
    assert rejected.reason == "Sliding window limit reached"
    assert governor.token_bucket.available == before


def test_governor_failure_creates_backoff_and_retry_budget():
    governor = RateLimitBackoffGovernor(
        capacity=10, refill_rate=10, base_delay=10, max_delay=10,
        jitter=JitterStrategy.NONE, max_retries=1,
    )
    governor.record_failure("api", 500)
    state = governor.get_backoff_state("api")
    assert state is not None and state.delay == 10
    assert governor.retry_budget.remaining == 0
    governor.record_failure("other", 500)
    assert governor.get_backoff_state("other") is None


def test_governor_honors_retry_after():
    governor = RateLimitBackoffGovernor(max_retries=2)
    governor.record_failure("api", 429, {"Retry-After": "12"})
    assert governor.get_backoff_state("api").delay == 12


def test_governor_reset_clears_state():
    governor = RateLimitBackoffGovernor(circuit_failure_threshold=1, circuit_recovery_timeout=100)
    governor.record_failure("api", 500)
    assert governor.circuit_breaker.state == CircuitState.OPEN
    governor.reset()
    assert governor.circuit_breaker.state == CircuitState.CLOSED
    assert governor.get_backoff_state("api") is None
