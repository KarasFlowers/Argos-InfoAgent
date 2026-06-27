"""Tests for CircuitBreaker state transitions and recovery."""

import time
from unittest.mock import patch

from app.services.llm.client import CircuitBreaker

URL = "https://api.example.com"
MODEL = "test-model"


class TestCircuitBreakerStates:
    """Verify closed → open → half-open → closed/open transitions."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=60, open_seconds=180)
        assert not cb.is_open(URL, MODEL)

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_success(URL, MODEL)
        assert not cb.is_open(URL, MODEL)

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, open_seconds=9999)
        for _ in range(3):
            cb.record_failure(URL, MODEL)
        assert cb.is_open(URL, MODEL)

    def test_fewer_failures_stays_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure(URL, MODEL)
        cb.record_failure(URL, MODEL)
        assert not cb.is_open(URL, MODEL)

    def test_is_open_when_open(self):
        cb = CircuitBreaker(failure_threshold=1, open_seconds=9999)
        cb.record_failure(URL, MODEL)
        assert cb.is_open(URL, MODEL)

    def test_half_open_after_open_expires(self):
        cb = CircuitBreaker(failure_threshold=1, open_seconds=0)
        cb.record_failure(URL, MODEL)
        time.sleep(0.01)
        # open_seconds=0 means circuit transitions to half-open immediately
        assert not cb.is_open(URL, MODEL)

    def test_success_closes_after_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, open_seconds=0)
        cb.record_failure(URL, MODEL)
        time.sleep(0.01)
        assert not cb.is_open(URL, MODEL)  # half-open
        cb.record_success(URL, MODEL)
        assert not cb.is_open(URL, MODEL)  # closed

    def test_failure_reopens_after_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, open_seconds=0.01)
        with patch("app.services.llm.client.time.monotonic") as monotonic:
            monotonic.side_effect = [0.0, 0.02, 0.021, 0.022]
            cb.record_failure(URL, MODEL)
            assert not cb.is_open(URL, MODEL)  # half-open
            cb.record_failure(URL, MODEL)
            assert cb.is_open(URL, MODEL)  # re-opened

    def test_rolling_window_expiry(self):
        """Failures outside rolling window should not count."""
        cb = CircuitBreaker(failure_threshold=3, window_seconds=0.05, open_seconds=9999)
        with patch("app.services.llm.client.time.monotonic") as monotonic:
            monotonic.side_effect = [0.0, 0.01, 0.07]
            cb.record_failure(URL, MODEL)
            cb.record_failure(URL, MODEL)
            cb.record_failure(URL, MODEL)
        # Only 1 failure within window
        assert not cb.is_open(URL, MODEL)

    def test_different_keys_independent(self):
        """Different (url, model) pairs should not interfere."""
        cb = CircuitBreaker(failure_threshold=1, open_seconds=9999)
        cb.record_failure(URL, MODEL)
        assert cb.is_open(URL, MODEL)
        assert not cb.is_open("https://other.com", "other-model")
