#!/usr/bin/env python3
"""Tests for Rate Limit Backoff Governor."""
import sys
import os
import unittest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rate_limit_governor import (
    TokenBucket, SlidingWindowRateLimiter, ExponentialBackoff,
    CircuitBreaker, RetryBudgetManager, RateLimitHeaderParser,
    AdaptiveRateLimiter, RateLimitBackoffGovernor,
    JitterStrategy, BackoffStrategy, CircuitState,
)


class TestTokenBucket(unittest.TestCase):
    def test_consume_within_capacity(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(5):
            self.assertTrue(bucket.consume())
        self.assertFalse(bucket.consume())

    def test_refill(self):
        bucket = TokenBucket(capacity=5, refill_rate=100.0)
        for _ in range(5):
            bucket.consume()
        self.assertFalse(bucket.consume())
        time.sleep(0.1)
        self.assertTrue(bucket.consume())

    def test_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        self.assertAlmostEqual(bucket.available, 10.0, places=0)
        bucket.consume(3)
        self.assertAlmostEqual(bucket.available, 7.0, places=0)

    def test_time_until_tokens(self):
        bucket = TokenBucket(capacity=5, refill_rate=2.0)
        for _ in range(5):
            bucket.consume()
        wait = bucket.time_until_tokens(1)
        self.assertGreater(wait, 0)
        self.assertLess(wait, 1.0)

    def test_reset(self):
        bucket = TokenBucket(capacity=5, refill_rate=1.0)
        for _ in range(5):
            bucket.consume()
        bucket.reset()
        self.assertTrue(bucket.consume())

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            TokenBucket(capacity=0, refill_rate=1.0)

    def test_invalid_refill_rate(self):
        with self.assertRaises(ValueError):
            TokenBucket(capacity=5, refill_rate=-1.0)


class TestSlidingWindowRateLimiter(unittest.TestCase):
    def test_allow_within_limit(self):
        limiter = SlidingWindowRateLimiter(window_sec=1.0, max_requests=5)
        for _ in range(5):
            self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_remaining(self):
        limiter = SlidingWindowRateLimiter(window_sec=1.0, max_requests=5)
        self.assertEqual(limiter.remaining, 5)
        limiter.allow()
        self.assertEqual(limiter.remaining, 4)

    def test_window_expires(self):
        limiter = SlidingWindowRateLimiter(window_sec=0.1, max_requests=2)
        limiter.allow()
        limiter.allow()
        self.assertFalse(limiter.allow())
        time.sleep(0.15)
        self.assertTrue(limiter.allow())

    def test_reset(self):
        limiter = SlidingWindowRateLimiter(window_sec=1.0, max_requests=2)
        limiter.allow()
        limiter.allow()
        limiter.reset()
        self.assertEqual(limiter.remaining, 2)


class TestExponentialBackoff(unittest.TestCase):
    def test_exponential_growth(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=60.0,
                                jitter=JitterStrategy.NONE)
        d0 = bo.calculate_delay(0)
        d1 = bo.calculate_delay(1)
        d2 = bo.calculate_delay(2)
        self.assertAlmostEqual(d0, 1.0, places=1)
        self.assertAlmostEqual(d1, 2.0, places=1)
        self.assertAlmostEqual(d2, 4.0, places=1)

    def test_max_delay_cap(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=10.0,
                                jitter=JitterStrategy.NONE)
        d = bo.calculate_delay(20)
        self.assertLessEqual(d, 10.0)

    def test_linear_strategy(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=60.0,
                                strategy=BackoffStrategy.LINEAR,
                                jitter=JitterStrategy.NONE)
        d0 = bo.calculate_delay(0)
        d1 = bo.calculate_delay(1)
        d2 = bo.calculate_delay(2)
        self.assertAlmostEqual(d0, 1.0, places=1)
        self.assertAlmostEqual(d1, 2.0, places=1)
        self.assertAlmostEqual(d2, 3.0, places=1)

    def test_fibonacci_strategy(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=100.0,
                                strategy=BackoffStrategy.FIBONACCI,
                                jitter=JitterStrategy.NONE)
        d0 = bo.calculate_delay(0)
        d1 = bo.calculate_delay(1)
        self.assertGreater(d0, 0)
        self.assertGreater(d1, d0)

    def test_full_jitter(self):
        bo = ExponentialBackoff(base_delay=10.0, max_delay=100.0,
                                jitter=JitterStrategy.FULL)
        delays = [bo.calculate_delay(3) for _ in range(100)]
        self.assertGreater(max(delays), 0)
        self.assertLess(max(delays), 81)

    def test_equal_jitter(self):
        bo = ExponentialBackoff(base_delay=10.0, max_delay=100.0,
                                jitter=JitterStrategy.EQUAL)
        delays = [bo.calculate_delay(2) for _ in range(100)]
        self.assertGreater(min(delays), 4.9)

    def test_decorrelated_jitter(self):
        bo = ExponentialBackoff(base_delay=1.0, max_delay=100.0,
                                jitter=JitterStrategy.DECORRELATED)
        delays = [bo.calculate_delay(3) for _ in range(100)]
        self.assertGreater(min(delays), 0)


class TestCircuitBreaker(unittest.TestCase):
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.allow_request())

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        time.sleep(0.15)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        self.assertTrue(cb.allow_request())

    def test_closes_after_successful_recovery(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, half_open_max=2)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.record_success()
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_reopens_on_failure_in_half_open(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_success_decrements_failures(self):
        cb = CircuitBreaker(failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.failure_count, 2)
        cb.record_success()
        self.assertEqual(cb.failure_count, 1)

    def test_get_state_info(self):
        cb = CircuitBreaker(failure_threshold=5)
        info = cb.get_state_info()
        self.assertEqual(info["state"], "closed")
        self.assertEqual(info["failure_threshold"], 5)


class TestRetryBudgetManager(unittest.TestCase):
    def test_can_retry_within_budget(self):
        budget = RetryBudgetManager(max_retries=3, window_sec=1.0)
        self.assertTrue(budget.can_retry())
        budget.record_retry()
        budget.record_retry()
        budget.record_retry()
        self.assertFalse(budget.can_retry())

    def test_remaining(self):
        budget = RetryBudgetManager(max_retries=5, window_sec=1.0)
        self.assertEqual(budget.remaining, 5)
        budget.record_retry()
        self.assertEqual(budget.remaining, 4)

    def test_window_expires(self):
        budget = RetryBudgetManager(max_retries=2, window_sec=0.1)
        budget.record_retry()
        budget.record_retry()
        self.assertFalse(budget.can_retry())
        time.sleep(0.15)
        self.assertTrue(budget.can_retry())

    def test_reset(self):
        budget = RetryBudgetManager(max_retries=2, window_sec=1.0)
        budget.record_retry()
        budget.record_retry()
        budget.reset()
        self.assertEqual(budget.remaining, 2)


class TestRateLimitHeaderParser(unittest.TestCase):
    def test_parse_standard_headers(self):
        headers = {
            "X-RateLimit-Limit": "100",
            "X-RateLimit-Remaining": "50",
            "X-RateLimit-Reset": "1700000000",
        }
        parsed = RateLimitHeaderParser.parse(headers)
        self.assertEqual(parsed.limit, 100)
        self.assertEqual(parsed.remaining, 50)
        self.assertEqual(parsed.reset, 1700000000.0)

    def test_parse_retry_after(self):
        headers = {"Retry-After": "30"}
        parsed = RateLimitHeaderParser.parse(headers)
        self.assertEqual(parsed.retry_after, 30.0)

    def test_parse_empty_headers(self):
        parsed = RateLimitHeaderParser.parse({})
        self.assertIsNone(parsed.limit)
        self.assertIsNone(parsed.remaining)
        self.assertIsNone(parsed.retry_after)

    def test_parse_invalid_values(self):
        headers = {"X-RateLimit-Limit": "not_a_number"}
        parsed = RateLimitHeaderParser.parse(headers)
        self.assertIsNone(parsed.limit)


class TestAdaptiveRateLimiter(unittest.TestCase):
    def test_initial_limit(self):
        al = AdaptiveRateLimiter(base_limit=100)
        self.assertEqual(al.current_limit, 100)

    def test_reduces_on_429(self):
        al = AdaptiveRateLimiter(base_limit=100)
        for _ in range(10):
            al.record_response(429)
        self.assertLess(al.current_limit, 100)

    def test_reduces_on_high_error_rate(self):
        al = AdaptiveRateLimiter(base_limit=100)
        for _ in range(10):
            al.record_response(500)
        self.assertLess(al.current_limit, 100)

    def test_increases_on_low_error_rate(self):
        al = AdaptiveRateLimiter(base_limit=100)
        for _ in range(30):
            al.record_response(200)
        self.assertGreaterEqual(al.current_limit, 100)

    def test_reset(self):
        al = AdaptiveRateLimiter(base_limit=100)
        for _ in range(10):
            al.record_response(429)
        al.reset()
        self.assertEqual(al.current_limit, 100)


class TestRateLimitBackoffGovernor(unittest.TestCase):
    def test_check_request_allowed(self):
        gov = RateLimitBackoffGovernor(capacity=10, refill_rate=10.0, max_requests=100)
        decision = gov.check_request()
        self.assertTrue(decision.allowed)

    def test_check_request_after_failures(self):
        gov = RateLimitBackoffGovernor(capacity=10, refill_rate=10.0, max_requests=100)
        for _ in range(5):
            gov.record_failure("api", status_code=500)
        decision = gov.check_request("api")
        self.assertFalse(decision.allowed)

    def test_circuit_breaker_integration(self):
        gov = RateLimitBackoffGovernor(capacity=100, refill_rate=100.0,
                                       max_requests=1000, circuit_failure_threshold=3)
        for _ in range(3):
            gov.record_failure("api", status_code=500)
        decision = gov.check_request("api")
        self.assertFalse(decision.allowed)
        self.assertIn("Circuit", decision.reason)

    def test_get_status(self):
        gov = RateLimitBackoffGovernor()
        status = gov.get_status()
        self.assertIn("token_bucket", status)
        self.assertIn("sliding_window", status)
        self.assertIn("circuit_breaker", status)
        self.assertIn("retry_budget", status)

    def test_reset(self):
        gov = RateLimitBackoffGovernor(capacity=10, refill_rate=10.0, max_requests=100)
        gov.record_failure("api", status_code=500)
        gov.reset()
        decision = gov.check_request("api")
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
