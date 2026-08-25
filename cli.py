#!/usr/bin/env python3
"""CLI for Agent Rate Limit Backoff Governor."""
import argparse
import json
import sys
from rate_limit_governor import (
    RateLimitBackoffGovernor, JitterStrategy, BackoffStrategy,
    CircuitBreaker, RetryBudgetManager, RateLimitHeaderParser,
)


def cmd_check(args):
    gov = RateLimitBackoffGovernor(
        capacity=args.capacity,
        refill_rate=args.refill_rate,
        max_requests=args.max_requests,
        base_delay=args.base_delay,
        max_delay=args.max_delay,
    )
    decision = gov.check_request(args.endpoint)
    print(f"Allowed: {decision.allowed}")
    print(f"Reason: {decision.reason}")
    print(f"Remaining: {decision.remaining}")
    print(f"Delay: {decision.delay:.2f}s")
    print(f"Circuit: {decision.circuit_state}")


def cmd_status(args):
    gov = RateLimitBackoffGovernor(
        capacity=args.capacity,
        refill_rate=args.refill_rate,
        max_requests=args.max_requests,
    )
    status = gov.get_status()
    print(json.dumps(status, indent=2))


def cmd_circuit(args):
    cb = CircuitBreaker(failure_threshold=args.threshold, recovery_timeout=args.timeout)
    print(f"Circuit Breaker State: {cb.state.value}")
    print(f"Failure threshold: {cb.failure_threshold}")
    for i in range(args.threshold + 1):
        state = cb.record_failure()
        print(f"  Failure {i + 1}: state={state.value}")
    print(f"Allow request: {cb.allow_request()}")


def cmd_backoff(args):
    from rate_limit_governor import ExponentialBackoff
    jitter = JitterStrategy(args.jitter)
    bo = ExponentialBackoff(base_delay=args.base_delay, max_delay=args.max_delay, jitter=jitter)
    for attempt in range(args.attempts):
        delay = bo.calculate_delay(attempt)
        print(f"  Attempt {attempt}: delay={delay:.3f}s")


def cmd_parse_headers(args):
    headers = json.loads(args.headers)
    parsed = RateLimitHeaderParser.parse(headers)
    print(f"Limit: {parsed.limit}")
    print(f"Remaining: {parsed.remaining}")
    print(f"Reset: {parsed.reset}")
    print(f"Retry-After: {parsed.retry_after}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="agent-rate-limit-backoff-governor",
        description="Rate limiting with token bucket, sliding window, exponential backoff, and circuit breaker"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_check = subparsers.add_parser("check", help="Check if a request is allowed")
    p_check.add_argument("--endpoint", default="default")
    p_check.add_argument("--capacity", type=int, default=10)
    p_check.add_argument("--refill-rate", type=float, default=1.0)
    p_check.add_argument("--max-requests", type=int, default=100)
    p_check.add_argument("--base-delay", type=float, default=1.0)
    p_check.add_argument("--max-delay", type=float, default=60.0)

    p_status = subparsers.add_parser("status", help="Show governor status")
    p_status.add_argument("--capacity", type=int, default=10)
    p_status.add_argument("--refill-rate", type=float, default=1.0)
    p_status.add_argument("--max-requests", type=int, default=100)

    p_circuit = subparsers.add_parser("circuit", help="Demo circuit breaker")
    p_circuit.add_argument("--threshold", type=int, default=5)
    p_circuit.add_argument("--timeout", type=float, default=30.0)

    p_backoff = subparsers.add_parser("backoff", help="Demo backoff delays")
    p_backoff.add_argument("--base-delay", type=float, default=1.0)
    p_backoff.add_argument("--max-delay", type=float, default=60.0)
    p_backoff.add_argument("--jitter", default="full", choices=["none", "full", "equal", "decorrelated"])
    p_backoff.add_argument("--attempts", type=int, default=8)

    p_headers = subparsers.add_parser("headers", help="Parse rate limit headers")
    p_headers.add_argument("--headers", required=True, help="JSON dict of headers")

    args = parser.parse_args(argv)

    if args.command == "check":
        cmd_check(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "circuit":
        cmd_circuit(args)
    elif args.command == "backoff":
        cmd_backoff(args)
    elif args.command == "headers":
        cmd_parse_headers(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
