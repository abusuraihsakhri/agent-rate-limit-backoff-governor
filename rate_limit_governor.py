#!/usr/bin/env python3
"""
Agent Rate Limit Backoff Governor: Token bucket, sliding window, exponential backoff
with jitter strategies, circuit breaker, retry budget, and adaptive rate limiting.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from enum import Enum
import time
import random
import math


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
class CircuitBreakerState:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_at: float = 0.0
    opened_at: float = 0.0


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
    """Token bucket rate limiter with configurable capacity and refill rate."""

    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens added per second
        """
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        if refill_rate < 0:
            raise ValueError("Refill rate must be non-negative")

        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    @property
    def available(self) -> float:
        self._refill()
        return self.tokens

    def time_until_tokens(self, tokens: int = 1) -> float:
        """Return seconds until the requested tokens are available."""
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        deficit = tokens - self.tokens
        return deficit / self.refill_rate if self.refill_rate > 0 else float('inf')

    def reset(self):
        self.tokens = float(self.capacity)
        self.last_refill = time.time()


class SlidingWindowRateLimiter:
    """Sliding window rate limiter using timestamp tracking."""

    def __init__(self, window_sec: float, max_requests: int):
        if window_sec <= 0:
            raise ValueError("Window must be positive")
        if max_requests <= 0:
            raise ValueError("Max requests must be positive")

        self.window_sec = window_sec
        self.max_requests = max_requests
        self.timestamps: List[float] = []

    def allow(self) -> bool:
        """Check if a request is allowed under the sliding window."""
        now = time.time()
        self._cleanup(now)
        if len(self.timestamps) < self.max_requests:
            self.timestamps.append(now)
            return True
        return False

    def _cleanup(self, now: float):
        cutoff = now - self.window_sec
        self.timestamps = [t for t in self.timestamps if t > cutoff]

    @property
    def current_count(self) -> int:
        now = time.time()
        self._cleanup(now)
        return len(self.timestamps)

    @property
    def remaining(self) -> int:
        return max(0, self.max_requests - self.current_count)

    def reset_at(self) -> float:
        """Return when the oldest request in the window expires."""
        if not self.timestamps:
            return time.time()
        return self.timestamps[0] + self.window_sec

    def reset(self):
        self.timestamps.clear()


class ExponentialBackoff:
    """Exponential backoff calculator with multiple jitter strategies."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0,
                 strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
                 jitter: JitterStrategy = JitterStrategy.FULL):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.strategy = strategy
        self.jitter = jitter
        self._fib_cache = [0, 1]

    def calculate_delay(self, attempt: int) -> float:
        """Calculate the backoff delay for the given attempt number."""
        if attempt < 0:
            attempt = 0

        if self.strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.base_delay * (2 ** attempt)
        elif self.strategy == BackoffStrategy.LINEAR:
            delay = self.base_delay * (attempt + 1)
        elif self.strategy == BackoffStrategy.FIBONACCI:
            delay = self.base_delay * self._fibonacci(attempt + 2)
        else:
            delay = self.base_delay * (2 ** attempt)

        delay = min(delay, self.max_delay)
        delay = self._apply_jitter(delay, attempt)
        return max(0.0, delay)

    def _apply_jitter(self, delay: float, attempt: int) -> float:
        if self.jitter == JitterStrategy.NONE:
            return delay
        elif self.jitter == JitterStrategy.FULL:
            return random.uniform(0, delay)
        elif self.jitter == JitterStrategy.EQUAL:
            return delay / 2 + random.uniform(0, delay / 2)
        elif self.jitter == JitterStrategy.DECORRELATED:
            return random.uniform(self.base_delay, delay * 3)
        return delay

    def _fibonacci(self, n: int) -> int:
        while len(self._fib_cache) <= n:
            self._fib_cache.append(self._fib_cache[-1] + self._fib_cache[-2])
        return self._fib_cache[n]


class CircuitBreaker:
    """Circuit breaker pattern: closed -> open -> half-open -> closed."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0,
                 half_open_max: int = 3):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_at = 0.0
        self.opened_at = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self.opened_at >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self.success_count = 0
        return self._state

    def record_success(self) -> CircuitState:
        """Record a successful request."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max:
                self._close()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)
        return self.state

    def record_failure(self) -> CircuitState:
        """Record a failed request."""
        current = self.state
        if current == CircuitState.HALF_OPEN:
            self._open()
        elif current == CircuitState.CLOSED:
            self.failure_count += 1
            self.last_failure_at = time.time()
            if self.failure_count >= self.failure_threshold:
                self._open()
        return self.state

    def _open(self):
        self._state = CircuitState.OPEN
        self.opened_at = time.time()

    def _close(self):
        self._state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0

    def allow_request(self) -> bool:
        """Check if a request should be allowed through the circuit."""
        state = self.state
        return state != CircuitState.OPEN

    def get_state_info(self) -> Dict:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class RetryBudgetManager:
    """Tracks retry attempts within a time window to prevent retry storms."""

    def __init__(self, max_retries: int = 5, window_sec: float = 60.0):
        self.max_retries = max_retries
        self.window_sec = window_sec
        self.retry_timestamps: List[float] = []

    def can_retry(self) -> bool:
        """Check if a retry is allowed within the budget."""
        self._cleanup()
        return len(self.retry_timestamps) < self.max_retries

    def record_retry(self):
        """Record a retry attempt."""
        self.retry_timestamps.append(time.time())

    def _cleanup(self):
        cutoff = time.time() - self.window_sec
        self.retry_timestamps = [t for t in self.retry_timestamps if t > cutoff]

    @property
    def remaining(self) -> int:
        self._cleanup()
        return max(0, self.max_retries - len(self.retry_timestamps))

    def reset(self):
        self.retry_timestamps.clear()


class RateLimitHeaderParser:
    """Parse rate limit headers from HTTP responses."""

    @staticmethod
    def parse(headers: Dict[str, str]) -> RateLimitHeaders:
        """Parse standard rate limit headers."""
        result = RateLimitHeaders()

        for key in headers:
            lower_key = key.lower().replace("-", "_")

            if lower_key in ("x_ratelimit_limit", "ratelimit_limit"):
                try:
                    result.limit = int(headers[key])
                except (ValueError, TypeError):
                    pass
            elif lower_key in ("x_ratelimit_remaining", "ratelimit_remaining"):
                try:
                    result.remaining = int(headers[key])
                except (ValueError, TypeError):
                    pass
            elif lower_key in ("x_ratelimit_reset", "ratelimit_reset"):
                try:
                    val = float(headers[key])
                    # If it looks like a Unix timestamp (large number), use as-is
                    if val > 1e9:
                        result.reset = val
                    else:
                        result.reset = time.time() + val
                except (ValueError, TypeError):
                    pass
            elif lower_key == "retry_after":
                try:
                    result.retry_after = float(headers[key])
                except (ValueError, TypeError):
                    pass

        return result


class AdaptiveRateLimiter:
    """Adapts rate limits based on response patterns and error rates."""

    def __init__(self, base_limit: int, window_sec: float = 60.0):
        self.base_limit = base_limit
        self.window_sec = window_sec
        self.current_limit = base_limit
        self.response_codes: List[int] = []
        self.timestamps: List[float] = []

    def record_response(self, status_code: int):
        """Record an HTTP response code for adaptive adjustment."""
        now = time.time()
        self.response_codes.append(status_code)
        self.timestamps.append(now)
        self._cleanup()
        self._adjust()

    def _cleanup(self):
        cutoff = time.time() - self.window_sec
        pairs = [(t, c) for t, c in zip(self.timestamps, self.response_codes) if t > cutoff]
        if pairs:
            self.timestamps, self.response_codes = zip(*pairs)
            self.timestamps = list(self.timestamps)
            self.response_codes = list(self.response_codes)
        else:
            self.timestamps = []
            self.response_codes = []

    def _adjust(self):
        if len(self.response_codes) < 5:
            return

        error_rate = sum(1 for c in self.response_codes if c >= 400) / len(self.response_codes)
        rate_limit_hits = sum(1 for c in self.response_codes if c == 429)

        if rate_limit_hits > 0:
            self.current_limit = max(1, int(self.current_limit * 0.5))
        elif error_rate > 0.5:
            self.current_limit = max(1, int(self.current_limit * 0.6))
        elif error_rate > 0.2:
            self.current_limit = max(1, int(self.current_limit * 0.8))
        elif error_rate < 0.05 and len(self.response_codes) >= 20:
            self.current_limit = min(self.base_limit * 2, int(self.current_limit * 1.1))

    def is_allowed(self) -> bool:
        """Check if a request is allowed under the adaptive limit."""
        self._cleanup()
        return len(self.timestamps) < self.current_limit

    def reset(self):
        self.current_limit = self.base_limit
        self.response_codes.clear()
        self.timestamps.clear()


class RateLimitBackoffGovernor:
    """Main governor combining all rate limiting and backoff mechanisms."""

    def __init__(self,
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
                 retry_window_sec: float = 60.0):
        self.token_bucket = TokenBucket(capacity, refill_rate)
        self.sliding_window = SlidingWindowRateLimiter(window_sec, max_requests)
        self.backoff = ExponentialBackoff(base_delay, max_delay, jitter=jitter)
        self.circuit_breaker = CircuitBreaker(circuit_failure_threshold, circuit_recovery_timeout)
        self.retry_budget = RetryBudgetManager(max_retries, retry_window_sec)
        self.adaptive = AdaptiveRateLimiter(max_requests, window_sec)
        self.header_parser = RateLimitHeaderParser()
        self._backoff_states: Dict[str, BackoffState] = {}

    def check_request(self, endpoint: str = "default") -> GovernorDecision:
        """Check if a request should be allowed."""
        # Check circuit breaker
        if not self.circuit_breaker.allow_request():
            return GovernorDecision(
                allowed=False,
                reason=f"Circuit breaker OPEN (failures: {self.circuit_breaker.failure_count})",
                delay=self.circuit_breaker.recovery_timeout,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        # Check backoff state
        if endpoint in self._backoff_states:
            state = self._backoff_states[endpoint]
            now = time.time()
            if now < state.next_retry_at:
                remaining_delay = state.next_retry_at - now
                return GovernorDecision(
                    allowed=False,
                    reason=f"Backoff active (attempt {state.attempt})",
                    delay=remaining_delay,
                    remaining=self.sliding_window.remaining,
                    circuit_state=self.circuit_breaker.state.value,
                    retry_budget_remaining=self.retry_budget.remaining,
                )

        # Check token bucket
        if not self.token_bucket.consume():
            delay = self.token_bucket.time_until_tokens(1)
            return GovernorDecision(
                allowed=False,
                reason="Token bucket empty",
                delay=delay,
                remaining=self.sliding_window.remaining,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        # Check sliding window
        if not self.sliding_window.allow():
            self.token_bucket.tokens = min(self.token_bucket.capacity,
                                           self.token_bucket.tokens + 1)
            return GovernorDecision(
                allowed=False,
                reason="Sliding window limit reached",
                delay=self.sliding_window.reset_at() - time.time(),
                remaining=0,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        # Check adaptive limit
        if not self.adaptive.is_allowed():
            self.token_bucket.tokens = min(self.token_bucket.capacity,
                                           self.token_bucket.tokens + 1)
            self.sliding_window.timestamps.pop()
            return GovernorDecision(
                allowed=False,
                reason="Adaptive limit reached",
                delay=1.0,
                remaining=0,
                circuit_state=self.circuit_breaker.state.value,
                retry_budget_remaining=self.retry_budget.remaining,
            )

        return GovernorDecision(
            allowed=True,
            reason="Allowed",
            remaining=self.sliding_window.remaining,
            circuit_state=self.circuit_breaker.state.value,
            retry_budget_remaining=self.retry_budget.remaining,
        )

    def record_success(self, endpoint: str = "default", status_code: int = 200,
                       headers: Optional[Dict[str, str]] = None):
        """Record a successful response."""
        self.circuit_breaker.record_success()
        self.adaptive.record_response(status_code)
        self._backoff_states.pop(endpoint, None)

        if headers:
            parsed = self.header_parser.parse(headers)
            if parsed.remaining is not None:
                pass  # Could adjust limits based on server hints
            if parsed.retry_after is not None:
                pass  # Server asking us to wait

    def record_failure(self, endpoint: str = "default", status_code: int = 500,
                       headers: Optional[Dict[str, str]] = None):
        """Record a failed response and compute backoff."""
        self.circuit_breaker.record_failure()
        self.adaptive.record_response(status_code)

        # Parse Retry-After header
        retry_after = None
        if headers:
            parsed = self.header_parser.parse(headers)
            if parsed.retry_after:
                retry_after = parsed.retry_after

        if not self.retry_budget.can_retry():
            return

        self.retry_budget.record_retry()

        current_state = self._backoff_states.get(endpoint, BackoffState())
        current_state.attempt += 1

        if retry_after:
            current_state.delay = retry_after
        else:
            current_state.delay = self.backoff.calculate_delay(current_state.attempt)

        current_state.next_retry_at = time.time() + current_state.delay
        current_state.total_waited += current_state.delay
        self._backoff_states[endpoint] = current_state

    def get_backoff_state(self, endpoint: str) -> Optional[BackoffState]:
        return self._backoff_states.get(endpoint)

    def reset(self):
        """Reset all governor state."""
        self.token_bucket.reset()
        self.sliding_window.reset()
        self.retry_budget.reset()
        self.adaptive.reset()
        self._backoff_states.clear()

    def get_status(self) -> Dict:
        """Return current governor status."""
        return {
            "token_bucket": {
                "available": round(self.token_bucket.available, 2),
                "capacity": self.token_bucket.capacity,
            },
            "sliding_window": {
                "current": self.sliding_window.current_count,
                "limit": self.sliding_window.max_requests,
                "remaining": self.sliding_window.remaining,
            },
            "circuit_breaker": self.circuit_breaker.get_state_info(),
            "retry_budget": {
                "remaining": self.retry_budget.remaining,
                "max": self.retry_budget.max_retries,
            },
            "adaptive_limit": self.adaptive.current_limit,
            "active_backoffs": len(self._backoff_states),
        }
