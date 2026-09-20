#!/usr/bin/env python3
"""Deterministic load simulator for the rate-limit governor."""
from __future__ import annotations

import argparse
import json
import random
from typing import Sequence

from rate_limit_governor import JitterStrategy, RateLimitBackoffGovernor


def run_simulation(requests: int = 100, failure_rate: float = 0.1, seed: int | None = None) -> dict:
    if requests <= 0:
        raise ValueError("requests must be positive")
    if not 0.0 <= failure_rate <= 1.0:
        raise ValueError("failure_rate must be between 0 and 1")

    rng = random.Random(seed)
    governor = RateLimitBackoffGovernor(
        capacity=20,
        refill_rate=1000.0,
        window_sec=1.0,
        max_requests=max(20, requests),
        base_delay=0.0,
        max_delay=0.0,
        jitter=JitterStrategy.NONE,
        circuit_failure_threshold=max(5, requests + 1),
        max_retries=requests,
        retry_window_sec=60.0,
    )

    allowed = throttled = successes = failures = 0
    reasons: dict[str, int] = {}
    for _ in range(requests):
        decision = governor.check_request("simulation")
        if not decision.allowed:
            throttled += 1
            reasons[decision.reason] = reasons.get(decision.reason, 0) + 1
            continue
        allowed += 1
        if rng.random() < failure_rate:
            failures += 1
            governor.record_failure("simulation", status_code=500)
        else:
            successes += 1
            governor.record_success("simulation", status_code=200)

    return {
        "requests": requests,
        "allowed": allowed,
        "throttled": throttled,
        "successes": successes,
        "failures": failures,
        "throttle_reasons": reasons,
        "final_status": governor.get_status(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic rate-limit simulation")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--failure-rate", type=float, default=0.1)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    print(json.dumps(run_simulation(args.requests, args.failure_rate, args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
