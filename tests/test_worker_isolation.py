"""Tests for process-isolated parser workers."""

import time

from core.worker_isolation import run_in_worker


def _echo_worker(value):
    return value


def _slow_worker():
    time.sleep(5)
    return "late"


def _instant_exit_worker():
    import os
    os._exit(1)


def test_run_in_worker_returns_value():
    outcome = run_in_worker(_echo_worker, "ok", timeout_seconds=5)

    assert outcome.ok is True
    assert outcome.value == "ok"
    assert outcome.timed_out is False


def test_run_in_worker_terminates_hanging_task():
    start = time.perf_counter()

    outcome = run_in_worker(_slow_worker, timeout_seconds=0.05)

    assert outcome.ok is False
    assert outcome.timed_out is True
    assert "timed out" in outcome.error
    assert time.perf_counter() - start < 4


def test_run_in_worker_detects_early_exit_without_full_timeout():
    start = time.perf_counter()

    outcome = run_in_worker(_instant_exit_worker, timeout_seconds=5)

    assert outcome.ok is False
    assert outcome.timed_out is False
    assert "exited without result" in outcome.error
    # Must not block for the full 5s timeout waiting on a dead worker.
    assert time.perf_counter() - start < 3
