#!/usr/bin/env python3
"""Rate limiting, backoff, circuit breaker, and retry-budget primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from math import isfinite
import random
import time
from typing import Dict, List, Mapping, Optional


class JitterStrategy(str, Enum):
    NONE = "none"
    FULL = "full"
    EQUAL = "equal"
    DECORRELATED = "decorrelated"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BackoffStrategy(str, Enum):
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIBONACCI = "fibonacci"


@dataclass
class RateLimitHeaders:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[float] = None
    retry_after: Optional[float] = None


@dataclass
class BackoffState:
    attempt: int = 0
    delay: float = 0.0
    next_retry_at: float = 0.0
    total_waited: float = 0.0


@dataclass
class RetryBudget:
    max_retries: int = 5
    window_sec: float = 60.0
    retry_timestamps: List[float] = field(default_factory=list)


@dataclass
class GovernorDecision:
    allowed: bool
    reason: str
    delay: float = 0.0
    remaining: int = 0
    circuit_state: str = "closed"
    retry_budget_remaining: int = 0


class TokenBucket:
    """Token-bucket limiter with fractional refill and bounded burst capacity."""

    def __init__(self, capacity: int, refill_rate: float):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate < 0 or not isfinite(refill_rate):
            raise ValueError("refill_rate must be a finite non-negative number")
        self.capacity = int(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        if tokens <= 0 or not isfinite(tokens):
            raise ValueError("tokens must be a finite positive number")
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available(self) -> float:
        self._refill()
        return self.tokens

    def time_until_tokens(self, tokens: float = 1.0) -> float:
        if tokens <= 0 or not isfinite(tokens):
            raise ValueError("tokens must be a finite positive number")
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        if self.refill_rate == 0:
            return float("inf")
        return (tokens - self.tokens) / self.refill_rate

    def reset(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()


class SlidingWindowRateLimiter:
    """Exact sliding-window request limiter backed by request timestamps."""

    def __init__(self, window_sec: float, max_requests: int):
        if window_sec <= 0 or not isfinite(window_sec):
            raise ValueError("window_sec must be a finite positive number")
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        self.window_sec = float(window_sec)
        self.max_requests = int(max_requests)
        self.timestamps: List[float] = []

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.window_sec
        self.timestamps = [stamp for stamp in self.timestamps if stamp > cutoff]

    def allow(self) -> bool:
        now = time.monotonic()
        self._cleanup(now)
        if len(self.timestamps) >= self.max_requests:
            return False
        self.timestamps.append(now)
        return True

    @property
    def current_count(self) -> int:
        now = time.monotonic()
        self._cleanup(now)
        return len(self.timestamps)

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - self.current_count)

    def time_until_available(self) -> float:
        now = time.monotonic()
        self._cleanup(now)
        if len(self.timestamps) < self.max_requests:
            return 0.0
        return max(0.0, self.timestamps[0] + self.window_sec - now)

    def reset_at(self) -> float:
        """Return an approximate wall-clock timestamp when a slot becomes available."""
        return time.time() + self.time_until_available()

    def undo_last(self) -> None:
        if self.timestamps:
            self.timestamps.pop()

    def reset(self) -> None:
        self.timestamps.clear()


class ExponentialBackoff:
    """Backoff calculator with exponential, linear, and Fibonacci schedules."""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
        jitter: JitterStrategy = JitterStrategy.FULL,
    ):
        if base_delay < 0 or not isfinite(base_delay):
            raise ValueError("base_delay must be a finite non-negative number")
        if max_delay < 0 or not isfinite(max_delay):
            raise ValueError("max_delay must be a finite non-negative number")
        if max_delay < base_delay:
            raise ValueError("max_delay must be greater than or equal to base_delay")
        self.base_delay = float(base_delay)
        self.max_delay = float(max_delay)
        self.strategy = BackoffStrategy(strategy)
        self.jitter = JitterStrategy(jitter)
        self._fib_cache = [0, 1]

    def calculate_delay(self, attempt: int, previous_delay: Optional[float] = None) -> float:
        attempt = max(0, int(attempt))
        if self.strategy == BackoffStrategy.EXPONENTIAL:
            raw_delay = self.base_delay * (2**attempt)
        elif self.strategy == BackoffStrategy.LINEAR:
            raw_delay = self.base_delay * (attempt + 1)
        else:
            raw_delay = self.base_delay * self._fibonacci(attempt + 2)

        delay = min(raw_delay, self.max_delay)
        if self.jitter == JitterStrategy.NONE:
            return delay
        if self.jitter == JitterStrategy.FULL:
            return random.uniform(0.0, delay)
        if self.jitter == JitterStrategy.EQUAL:
            return delay / 2.0 + random.uniform(0.0, delay / 2.0)

        previous = self.base_delay if previous_delay is None else max(self.base_delay, previous_delay)
        upper = min(self.max_delay, max(self.base_delay, previous * 3.0))
        return random.uniform(self.base_delay, upper) if upper > self.base_delay else self.base_delay

    def _fibonacci(self, n: int) -> int:
        while len(self._fib_cache) <= n:
            self._fib_cache.append(self._fib_cache[-1] + self._fib_cache[-2])
        return self._fib_cache[n]


class CircuitBreaker:
    """Three-state circuit breaker with bounded half-open probe requests."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, half_open_max: int = 3):
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout < 0 or not isfinite(recovery_timeout):
            raise ValueError("recovery_timeout must be a finite non-negative number")
        if half_open_max <= 0:
            raise ValueError("half_open_max must be positive")
        self.failure_threshold = int(failure_threshold)
        self.recovery_timeout = float(recovery_timeout)
        self.half_open_max = int(half_open_max)
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_at = 0.0
        self.opened_at = 0.0
        self._half_open_probes = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and time.monotonic() - self.opened_at >= self.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            self.success_count = 0
            self._half_open_probes = 0
        return self._state

    def time_until_retry(self) -> float:
        if self.state != CircuitState.OPEN:
            return 0.0
        return max(0.0, self.recovery_timeout - (time.monotonic() - self.opened_at))

    def allow_request(self) -> bool:
        current = self.state
        if current == CircuitState.OPEN:
            return False
        if current == CircuitState.HALF_OPEN:
            if self._half_open_probes >= self.half_open_max:
                return False
            self._half_open_probes += 1
        return True

    def record_success(self) -> CircuitState:
        current = self.state
        if current == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max:
                self._close()
        elif current == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)
        return self.state

    def record_failure(self) -> CircuitState:
        current = self.state
        if current == CircuitState.HALF_OPEN:
            self._open()
        elif current == CircuitState.CLOSED:
            self.failure_count += 1
            self.last_failure_at = time.monotonic()
            if self.failure_count >= self.failure_threshold:
                self._open()
        return self.state

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self.opened_at = time.monotonic()
        self._half_open_probes = 0

    def _close(self) -> None:
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self._half_open_probes = 0
        self.opened_at = 0.0

    def reset(self) -> None:
        self.last_failure_at = 0.0
        self._close()

    def get_state_info(self) -> Dict[str, float | int | str]:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "half_open_probes": self._half_open_probes,
        }


class RetryBudgetManager:
    """Bound retries over a rolling time window."""

    def __init__(self, max_retries: int = 5, window_sec: float = 60.0):
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if window_sec <= 0 or not isfinite(window_sec):
            raise ValueError("window_sec must be a finite positive number")
        self.max_retries = int(max_retries)
        self.window_sec = float(window_sec)
        self.retry_timestamps: List[float] = []

    def _cleanup(self) -> None:
        cutoff = time.monotonic() - self.window_sec
        self.retry_timestamps = [stamp for stamp in self.retry_timestamps if stamp > cutoff]

    def can_retry(self) -> bool:
        self._cleanup()
        return len(self.retry_timestamps) < self.max_retries

    def record_retry(self) -> bool:
        self._cleanup()
        if len(self.retry_timestamps) >= self.max_retries:
            return False
        self.retry_timestamps.append(time.monotonic())
        return True

    @property
    def remaining(self) -> int:
        self._cleanup()
        return max(0, self.max_retries - len(self.retry_timestamps))

    def reset(self) -> None:
        self.retry_timestamps.clear()


class RateLimitHeaderParser:
    """Parse common RateLimit and Retry-After response headers."""

    @staticmethod
    def parse(headers: Mapping[str, str]) -> RateLimitHeaders:
        normalized = {str(key).lower().replace("-", "_"): value for key, value in headers.items()}
        result = RateLimitHeaders()

        for key in ("x_ratelimit_limit", "ratelimit_limit"):
            if key in normalized:
                try:
                    result.limit = int(normalized[key])
                except (TypeError, ValueError):
                    pass
                break

        for key in ("x_ratelimit_remaining", "ratelimit_remaining"):
            if key in normalized:
                try:
                    result.remaining = int(normalized[key])
                except (TypeError, ValueError):
                    pass
                break

        for key in ("x_ratelimit_reset", "ratelimit_reset"):
            if key in normalized:
                try:
                    value = float(normalized[key])
                    result.reset = value if value > 1_000_000_000 else time.time() + max(0.0, value)
                except (TypeError, ValueError):
                    pass
                break

        if "retry_after" in normalized:
            raw = normalized["retry_after"]
            try:
                result.retry_after = max(0.0, float(raw))
            except (TypeError, ValueError):
                try:
                    retry_time = parsedate_to_datetime(str(raw))
                    if retry_time.tzinfo is None:
                        retry_time = retry_time.replace(tzinfo=timezone.utc)  # pragma: no cover
                    result.retry_after = max(0.0, retry_time.timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        return result


class AdaptiveRateLimiter:
    """AIMD-style adaptive request ceiling informed by recent responses."""

    def __init__(self, base_limit: int, window_sec: float = 60.0):
        if base_limit <= 0:
            raise ValueError("base_limit must be positive")
        if window_sec <= 0 or not isfinite(window_sec):
            raise ValueError("window_sec must be a finite positive number")
        self.base_limit = int(base_limit)
        self.window_sec = float(window_sec)
        self.current_limit = int(base_limit)
        self.request_timestamps: List[float] = []
        self.response_codes: List[int] = []
        self.response_timestamps: List[float] = []
        self._success_streak = 0

    def _cleanup_requests(self) -> None:
        cutoff = time.monotonic() - self.window_sec
        self.request_timestamps = [stamp for stamp in self.request_timestamps if stamp > cutoff]

    def _cleanup_responses(self) -> None:
        cutoff = time.monotonic() - self.window_sec
        pairs = [(stamp, code) for stamp, code in zip(self.response_timestamps, self.response_codes) if stamp > cutoff]
        if pairs:
            self.response_timestamps, self.response_codes = map(list, zip(*pairs))
        else:
            self.response_timestamps = []
            self.response_codes = []

    def is_allowed(self) -> bool:
        self._cleanup_requests()
        return len(self.request_timestamps) < self.current_limit

    def record_request(self) -> None:
        self._cleanup_requests()
        self.request_timestamps.append(time.monotonic())

    def record_response(self, status_code: int) -> None:
        code = int(status_code)
        self.response_timestamps.append(time.monotonic())
        self.response_codes.append(code)
        self._cleanup_responses()

        if code == 429:
            self.current_limit = max(1, self.current_limit // 2)
            self._success_streak = 0
            return
        if code >= 500:
            self._success_streak = 0
            if len(self.response_codes) >= 5:
                errors = sum(value >= 500 for value in self.response_codes)
                if errors / len(self.response_codes) > 0.5:
                    self.current_limit = max(1, int(self.current_limit * 0.8))
            return
        if 200 <= code < 400:
            self._success_streak += 1
            if self._success_streak >= 20 and self.current_limit < self.base_limit * 2:
                self.current_limit += 1
                self._success_streak = 0
        else:
            self._success_streak = 0

    def reset(self) -> None:
        self.current_limit = self.base_limit
        self.request_timestamps.clear()
        self.response_codes.clear()
        self.response_timestamps.clear()
        self._success_streak = 0


class RateLimitBackoffGovernor:
    """Combine token bucket, sliding window, adaptive limiting, backoff, and a circuit breaker."""

    def __init__(
        self,
        capacity: int = 10,
        refill_rate: float = 1.0,
        window_sec: float = 60.0,
        max_requests: int = 100,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: JitterStrategy = JitterStrategy.FULL,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 30.0,
        max_retries: int = 5,
        retry_window_sec: float = 60.0,
    ):
        self.token_bucket = TokenBucket(capacity, refill_rate)
        self.sliding_window = SlidingWindowRateLimiter(window_sec, max_requests)
        self.backoff = ExponentialBackoff(base_delay, max_delay, jitter=jitter)
        self.circuit_breaker = CircuitBreaker(circuit_failure_threshold, circuit_recovery_timeout)
        self.retry_budget = RetryBudgetManager(max_retries, retry_window_sec)
        self.adaptive = AdaptiveRateLimiter(max_requests, window_sec)
        self.header_parser = RateLimitHeaderParser()
        self._backoff_states: Dict[str, BackoffState] = {}

    def check_request(self, endpoint: str = "default") -> GovernorDecision:
        if not self.circuit_breaker.allow_request():
            return GovernorDecision(
                allowed=False,
                reason=f"Circuit breaker {self.circuit_breaker.state.value.upper()}",
                delay=self.circuit_breaker.time_until_retry(),
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        state = self._backoff_states.get(endpoint)
        if state is not None:
            remaining_delay = state.next_retry_at - time.monotonic()
            if remaining_delay > 0:
                return GovernorDecision(
                    allowed=False,
                    reason=f"Backoff active (attempt {state.attempt})",
                    delay=remaining_delay,
                    remaining=self.sliding_window.remaining,
                    circuit_state=self.circuit_breaker.state.value,
                    retry_budget_remaining=self.retry_budget.remaining,
                )

        if not self.token_bucket.consume():
            return GovernorDecision(
                allowed=False,
                reason="Token bucket empty",
                delay=self.token_bucket.time_until_tokens(1),
                remaining=self.sliding_window.remaining,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        if not self.sliding_window.allow():
            self.token_bucket.tokens = min(self.token_bucket.capacity, self.token_bucket.tokens + 1.0)
            return GovernorDecision(
                allowed=False,
                reason="Sliding window limit reached",
                delay=self.sliding_window.time_until_available(),
                remaining=0,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        if not self.adaptive.is_allowed():
            self.token_bucket.tokens = min(self.token_bucket.capacity, self.token_bucket.tokens + 1.0)
            self.sliding_window.undo_last()
            return GovernorDecision(
                allowed=False,
                reason="Adaptive limit reached",
                delay=self.sliding_window.time_until_available(),
                remaining=self.sliding_window.remaining,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        self.adaptive.record_request()
        return GovernorDecision(
            allowed=True,
            reason="Allowed",
            remaining=self.sliding_window.remaining,
            circuit_state=self.circuit_breaker.state.value,
            retry_budget_remaining=self.retry_budget.remaining,
        )

    def record_success(self, endpoint: str = "default", status_code: int = 200, headers: Optional[Mapping[str, str]] = None) -> None:
        self.circuit_breaker.record_success()
        self.adaptive.record_response(status_code)
        self._backoff_states.pop(endpoint, None)
        if headers:
            self.header_parser.parse(headers)

    def record_failure(self, endpoint: str = "default", status_code: int = 500, headers: Optional[Mapping[str, str]] = None) -> None:
        self.circuit_breaker.record_failure()
        self.adaptive.record_response(status_code)

        retry_after: Optional[float] = None
        if headers:
            retry_after = self.header_parser.parse(headers).retry_after

        if not self.retry_budget.record_retry():
            return

        state = self._backoff_states.get(endpoint, BackoffState())
        previous_delay = state.delay if state.attempt > 0 else None
        state.attempt += 1
        state.delay = retry_after if retry_after is not None else self.backoff.calculate_delay(state.attempt - 1, previous_delay)
        state.next_retry_at = time.monotonic() + state.delay
        state.total_waited += state.delay
        self._backoff_states[endpoint] = state

    def get_backoff_state(self, endpoint: str) -> Optional[BackoffState]:
        return self._backoff_states.get(endpoint)

    def reset(self) -> None:
        self.token_bucket.reset()
        self.sliding_window.reset()
        self.circuit_breaker.reset()
        self.retry_budget.reset()
        self.adaptive.reset()
        self._backoff_states.clear()

    def get_status(self) -> Dict[str, object]:
        return {
            "token_bucket": {"available": round(self.token_bucket.available, 2), "capacity": self.token_bucket.capacity},
            "sliding_window": {
                "current": self.sliding_window.current_count,
                "limit": self.sliding_window.max_requests,
                "remaining": self.sliding_window.remaining,
            },
            "circuit_breaker": self.circuit_breaker.get_state_info(),
            "retry_budget": {"remaining": self.retry_budget.remaining, "max": self.retry_budget.max_retries},
            "adaptive_limit": self.adaptive.current_limit,
            "active_backoffs": len(self._backoff_states),
        }


__all__ = [
    "AdaptiveRateLimiter",
    "BackoffState",
    "BackoffStrategy",
    "CircuitBreaker",
    "CircuitState",
    "ExponentialBackoff",
    "GovernorDecision",
    "JitterStrategy",
    "RateLimitBackoffGovernor",
    "RateLimitHeaderParser",
    "RateLimitHeaders",
    "RetryBudget",
    "RetryBudgetManager",
    "SlidingWindowRateLimiter",
    "TokenBucket",
]
