# Agent Rate Limit Backoff Governor

A small Python library and command-line tool for request throttling, retry backoff, circuit breaking, and retry-budget control. The repository also includes a dependency-free browser simulator for exploring the algorithms interactively.

## What it includes

- Token-bucket rate limiting with fractional refill rates and burst capacity.
- Sliding-window request limits.
- Exponential, linear, and Fibonacci retry schedules.
- No jitter, full jitter, equal jitter, and capped decorrelated jitter.
- Circuit breaker states with bounded half-open probes and timed recovery.
- Retry budgets over rolling time windows.
- Parsing of common `RateLimit-*`, `X-RateLimit-*`, and `Retry-After` headers, including HTTP-date values.
- Adaptive request ceilings that respond to `429` and server-error responses.
- A local browser simulator with light/dark themes and no external JavaScript dependencies.

## Browser simulator

Open `index.html` directly or serve the repository with a static HTTP server:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/`.

The browser interface runs entirely on the device. It does not upload configuration or simulation data and makes no external API requests.

## Installation

Python 3.10 or newer is required. The runtime library uses only the Python standard library.

```bash
git clone https://github.com/abusuraihsakhri/agent-rate-limit-backoff-governor.git
cd agent-rate-limit-backoff-governor
python -m pip install -e .
```

## Command line

```bash
rate-limit-governor status
rate-limit-governor check --endpoint api/v1/query --capacity 10 --refill-rate 2
rate-limit-governor backoff --strategy exponential --jitter decorrelated --attempts 6
rate-limit-governor headers --headers '{"Retry-After":"30","X-RateLimit-Remaining":"4"}'
python simulator.py --requests 100 --failure-rate 0.1 --seed 7
```

The legacy entry points `python cli.py ...` and `python ratelimit_governor_app.py ...` remain available as compatibility wrappers.

## Python API

```python
from rate_limit_governor import RateLimitBackoffGovernor

governor = RateLimitBackoffGovernor(
    capacity=20,
    refill_rate=5.0,
    max_requests=100,
    base_delay=0.5,
    max_delay=30.0,
)

decision = governor.check_request("upstream-api")
if decision.allowed:
    # Perform the request, then record its response.
    governor.record_success("upstream-api", status_code=200)
else:
    print(decision.reason, decision.delay)
```

`check_request()` reserves rate-limit capacity for an allowed request. Call `record_success()` or `record_failure()` after the corresponding upstream response so adaptive and circuit-breaker state stays current.

## Development and testing

```bash
python -m pip install -e . pytest
python -m pytest -q
python -m compileall -q rate_limit_governor.py ratelimit_governor cli.py simulator.py
node --check app.js
```

GitHub Actions runs the test suite on Python 3.10, 3.12, and 3.14 and performs CLI and JavaScript syntax smoke tests.

## Technology

- Python standard library for the runtime package.
- HTML, CSS, and vanilla JavaScript for the browser simulator.
- GitHub Actions for continuous integration and GitHub Pages deployment.

The browser interface is designed for current versions of Chrome, Edge, Firefox, and Safari. No browser Python runtime is required.

## License

MIT. See [LICENSE](LICENSE).
