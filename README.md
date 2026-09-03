# Agent Rate Limit Backoff Governor

A pure Python production-grade rate limiting and adaptive resilience engine implementing:
- Token-Bucket rate limiting with sub-second token replenishment and burst handling.
- Sliding Window counter rate limiting for smooth temporal request spreading.
- Exponential backoff with multiple jitter strategies (Full Jitter, Equal Jitter, Decorrelated Jitter).
- Three-state Circuit Breaker pattern (`CLOSED`, `OPEN`, `HALF_OPEN`) with automated recovery timeouts.
- Retry budget management enforcing maximum failure ratios over rolling time windows.
- Standard rate-limit header parsing (RFC 6585, Draft IETF, and vendor variants like `X-RateLimit-*`, `Retry-After`).
- AIMD (Additive Increase / Multiplicative Decrease) adaptive rate limiting responding dynamically to `429 Too Many Requests` and server error codes.

Requires Python standard library only (zero external runtime dependencies).

---

## Features

- **Token Bucket Algorithm:** Enforces steady-state rate limits while permitting controlled burst capacity without starving callers.
- **Decorrelated Jitter Backoff:** Eliminates synchronized thundering herd spikes on downstream API endpoints by dynamically computing:
  $$\text{Sleep} = \min(\text{max\_delay}, \text{Uniform}(\text{base\_delay}, \text{previous\_delay} \times 3))$$
- **Circuit Breaker:** Halts outbound requests upon consecutive failure thresholds to protect impaired upstream services and permits probe requests during half-open states.
- **Header Parsing:** Automatically extracts rate limit quotas and calculates countdown resets from HTTP headers.
- **Batch CSV Processing:** High-throughput validation and telemetry auditing for API request workloads.

---

## Installation & Requirements

- Python 3.10+ (tested on 3.10, 3.11, 3.12)
- Zero external runtime dependencies. `pytest` is optional for running tests.

```bash
git clone https://github.com/abusuraihsakhri/agent-rate-limit-backoff-governor.git
cd agent-rate-limit-backoff-governor
```

---

## CLI Usage

### 1. Check Rate Limit Decision
Check whether a request to an endpoint is permitted:
```bash
python cli.py check --endpoint api/v1/query --capacity 10 --refill-rate 2.0
```

### 2. View Governor Status
Inspect status of Token Bucket, Sliding Window, Circuit Breakers, and Retry Budgets:
```bash
python cli.py status
```

### 3. Circuit Breaker Simulation
Simulate failures and state transitions:
```bash
python cli.py circuit --threshold 3 --timeout 5.0
```

### 4. Exponential Jitter Delay Simulation
Calculate backoff delays across multiple retry attempts:
```bash
python cli.py backoff --base-delay 1.0 --max-delay 60.0 --attempts 5 --jitter full
```

### 5. Multi-Agent Telemetry Audit
Run supervisory audit with JSON output:
```bash
python ratelimit_governor_app.py audit --task-id TASK-2026-001 --primary 29.4 --secondary 15.1 --json
```

### 6. Batch CSV Processing
Batch process request metrics and save results:
```bash
python ratelimit_governor_app.py batch -i sample.csv -o results.csv
```

---

## Python API Quickstart

```python
from rate_limit_governor import (
    RateLimitBackoffGovernor,
    ExponentialBackoff,
    JitterStrategy,
    CircuitBreaker,
)

# 1. Initialize Governor
governor = RateLimitBackoffGovernor(
    capacity=20,
    refill_rate=5.0,        # 5 tokens per second
    max_requests=100,       # 100 requests per minute
    base_delay=0.5,
    max_delay=30.0,
)

# 2. Check if request is allowed
decision = governor.check_request("llm_service")
if decision.allowed:
    print(f"Request permitted. Tokens remaining: {decision.remaining}")
else:
    print(f"Request throttled. Backoff delay: {decision.delay:.2f}s (Reason: {decision.reason})")

# 3. Decorrelated Jitter Backoff
backoff = ExponentialBackoff(base_delay=1.0, max_delay=30.0, jitter=JitterStrategy.DECORRELATED)
for attempt in range(4):
    delay = backoff.calculate_delay(attempt)
    print(f"Attempt {attempt + 1}: Sleep {delay:.3f}s")
```

---

## Running Tests

Run the test suite using standard `unittest` or `pytest`:

```bash
pytest -v
```

