"""Small process-isolation helper for untrusted parsers."""

from __future__ import annotations

import multiprocessing
import queue
import traceback
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class WorkerOutcome:
    ok: bool
    value: Any = None
    error: str = ""
    timed_out: bool = False


def run_in_worker(
    target: Callable[..., Any],
    *args: Any,
    timeout_seconds: float,
    **kwargs: Any,
) -> WorkerOutcome:
    """Run a top-level callable in a spawned process and enforce wall-clock timeout."""
    if timeout_seconds <= 0:
        return WorkerOutcome(ok=False, error="Worker timeout must be greater than zero")

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_worker_entrypoint,
        args=(target, args, kwargs, result_queue),
        daemon=True,
    )
    process.start()

    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty:
        timed_out = process.is_alive()
        if timed_out:
            process.terminate()
            process.join(1)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1)
        result_queue.close()
        result_queue.join_thread()
        if not timed_out:
            return WorkerOutcome(
                ok=False,
                error=f"Worker exited without result ({process.exitcode})",
            )
        return WorkerOutcome(
            ok=False,
            error=f"Worker timed out after {timeout_seconds:g}s",
            timed_out=True,
        )

    process.join(1)
    if process.is_alive():
        process.terminate()
        process.join(1)
    result_queue.close()
    result_queue.join_thread()

    if status == "ok":
        return WorkerOutcome(ok=True, value=payload)
    return WorkerOutcome(ok=False, error=str(payload))


def _worker_entrypoint(
    target: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result_queue,
) -> None:
    try:
        result_queue.put(("ok", target(*args, **kwargs)))
    except BaseException as exc:
        result_queue.put((
            "error",
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}",
        ))
