from datetime import datetime, timedelta

from core.circuit_breaker import CircuitBreaker, CircuitState


def test_circuit_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow_request()


def test_circuit_moves_from_open_to_half_open_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=600)
    breaker.record_failure()
    breaker.opened_at = datetime.now() - timedelta(seconds=601)
    assert breaker.allow_request()
    assert breaker.state == CircuitState.HALF_OPEN


def test_half_open_failure_returns_to_open() -> None:
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=600)
    breaker.record_failure()
    breaker.opened_at = datetime.now() - timedelta(seconds=601)
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
