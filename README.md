# Agent Rate Limit Backoff Governor

A comprehensive rate limiting and backoff system implementing token bucket, sliding window, exponential backoff with jitter strategies, circuit breaker, retry budget, and adaptive rate limiting.

## Features

- **Token bucket algorithm**: configurable capacity and refill rate
- **Sliding window rate limiter**: timestamp-based request tracking
- **Exponential backoff**: `delay = base × 2^attempt` with jitter
- **Jitter strategies**: none, full, equal, decorrelated
- **Circuit breaker**: closed → open → half-open state machine
- **Retry budget**: max retries per time window to prevent retry storms
- **Rate limit header parsing**: X-RateLimit-Remaining, Retry-After, etc.
- **Adaptive rate limiting**: adjusts limits based on response codes (429, 5xx)

## Quick Start

```bash
# Check if a request is allowed
python cli.py check --capacity 10 --refill-rate 2.0 --max-requests 100

# Show governor status
python cli.py status

# Demo circuit breaker
python cli.py circuit --threshold 5 --timeout 30

# Demo backoff delays
python cli.py backoff --jitter full --attempts 8

# Parse rate limit headers
python cli.py headers --headers '{"X-RateLimit-Remaining": "5", "Retry-After": "30"}'
```

## Python API

```python
from rate_limit_governor import RateLimitBackoffGovernor, JitterStrategy

gov = RateLimitBackoffGovernor(
    capacity=10,
    refill_rate=2.0,
    max_requests=100,
    base_delay=1.0,
    max_delay=60.0,
    jitter=JitterStrategy.FULL,
)

# Check request
decision = gov.check_request("api/users")
if decision.allowed:
    # Make the request...
    gov.record_success("api/users", status_code=200)
else:
    print(f"Blocked: {decision.reason}, wait {decision.delay:.1f}s")

# On failure
gov.record_failure("api/users", status_code=429,
                   headers={"Retry-After": "30"})

# Check status
print(gov.get_status())
```

## Architecture

```
RateLimitBackoffGovernor
├── TokenBucket           # Token bucket with capacity/refill
├── SlidingWindowRateLimiter  # Timestamp-based window
├── ExponentialBackoff    # Backoff with jitter strategies
├── CircuitBreaker        # closed/open/half-open states
├── RetryBudgetManager    # Retry limits per time window
├── AdaptiveRateLimiter   # Response-code-based adjustment
└── RateLimitHeaderParser # Parse standard rate limit headers
```

## License

MIT
