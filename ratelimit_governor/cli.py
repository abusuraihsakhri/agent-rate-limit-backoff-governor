"""Command-line interface for the rate-limit backoff governor."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from rate_limit_governor import (
    BackoffStrategy,
    CircuitBreaker,
    ExponentialBackoff,
    JitterStrategy,
    RateLimitBackoffGovernor,
    RateLimitHeaderParser,
)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _cmd_check(args: argparse.Namespace) -> int:
    governor = RateLimitBackoffGovernor(
        capacity=args.capacity,
        refill_rate=args.refill_rate,
        window_sec=args.window,
        max_requests=args.max_requests,
        base_delay=args.base_delay,
        max_delay=args.max_delay,
        jitter=JitterStrategy(args.jitter),
    )
    decision = governor.check_request(args.endpoint)
    result = {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "remaining": decision.remaining,
        "delay_seconds": round(decision.delay, 6),
        "circuit_state": decision.circuit_state,
        "retry_budget_remaining": decision.retry_budget_remaining,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    governor = RateLimitBackoffGovernor(
        capacity=args.capacity,
        refill_rate=args.refill_rate,
        window_sec=args.window,
        max_requests=args.max_requests,
    )
    print(json.dumps(governor.get_status(), indent=2))
    return 0


def _cmd_backoff(args: argparse.Namespace) -> int:
    backoff = ExponentialBackoff(
        base_delay=args.base_delay,
        max_delay=args.max_delay,
        strategy=BackoffStrategy(args.strategy),
        jitter=JitterStrategy(args.jitter),
    )
    previous = None
    rows = []
    for attempt in range(args.attempts):
        delay = backoff.calculate_delay(attempt, previous_delay=previous)
        rows.append({"attempt": attempt + 1, "delay_seconds": round(delay, 6)})
        previous = delay
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"attempt {row['attempt']}: {row['delay_seconds']:.6f}s")
    return 0


def _cmd_circuit(args: argparse.Namespace) -> int:
    breaker = CircuitBreaker(args.threshold, args.timeout, args.half_open_probes)
    for _ in range(args.failures):
        breaker.record_failure()
    print(json.dumps(breaker.get_state_info(), indent=2))
    return 0


def _cmd_headers(args: argparse.Namespace) -> int:
    try:
        headers = json.loads(args.headers)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON for --headers: {exc.msg}") from exc
    if not isinstance(headers, dict):
        raise SystemExit("--headers must decode to a JSON object")
    parsed = RateLimitHeaderParser.parse(headers)
    print(json.dumps({
        "limit": parsed.limit,
        "remaining": parsed.remaining,
        "reset": parsed.reset,
        "retry_after": parsed.retry_after,
    }, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rate-limit-governor",
        description="Inspect rate limits, backoff schedules, circuit-breaker state, and response headers.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Evaluate one request against a fresh governor")
    check.add_argument("--endpoint", default="default")
    check.add_argument("--capacity", type=_positive_int, default=10)
    check.add_argument("--refill-rate", type=_non_negative_float, default=1.0)
    check.add_argument("--window", type=float, default=60.0)
    check.add_argument("--max-requests", type=_positive_int, default=100)
    check.add_argument("--base-delay", type=_non_negative_float, default=1.0)
    check.add_argument("--max-delay", type=_non_negative_float, default=60.0)
    check.add_argument("--jitter", choices=[item.value for item in JitterStrategy], default=JitterStrategy.FULL.value)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=_cmd_check)

    status = sub.add_parser("status", help="Print the initial state of a governor")
    status.add_argument("--capacity", type=_positive_int, default=10)
    status.add_argument("--refill-rate", type=_non_negative_float, default=1.0)
    status.add_argument("--window", type=float, default=60.0)
    status.add_argument("--max-requests", type=_positive_int, default=100)
    status.set_defaults(func=_cmd_status)

    backoff = sub.add_parser("backoff", help="Generate a backoff schedule")
    backoff.add_argument("--base-delay", type=_non_negative_float, default=1.0)
    backoff.add_argument("--max-delay", type=_non_negative_float, default=60.0)
    backoff.add_argument("--strategy", choices=[item.value for item in BackoffStrategy], default=BackoffStrategy.EXPONENTIAL.value)
    backoff.add_argument("--jitter", choices=[item.value for item in JitterStrategy], default=JitterStrategy.FULL.value)
    backoff.add_argument("--attempts", type=_positive_int, default=8)
    backoff.add_argument("--json", action="store_true")
    backoff.set_defaults(func=_cmd_backoff)

    circuit = sub.add_parser("circuit", help="Apply failures to a circuit breaker and print its state")
    circuit.add_argument("--threshold", type=_positive_int, default=5)
    circuit.add_argument("--timeout", type=_non_negative_float, default=30.0)
    circuit.add_argument("--half-open-probes", type=_positive_int, default=3)
    circuit.add_argument("--failures", type=int, default=5)
    circuit.set_defaults(func=_cmd_circuit)

    headers = sub.add_parser("headers", help="Parse common rate-limit response headers")
    headers.add_argument("--headers", required=True, help='JSON object, e.g. {"Retry-After":"30"}')
    headers.set_defaults(func=_cmd_headers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
