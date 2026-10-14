"""Runs a pipeline in a worker thread and streams its progress as Server-Sent Events.

Events: `status` (progress), then one of `clarify`, `result` or `error`.
A comment line is sent while waiting, so proxies keep the stream open.
If the client goes away, the run is told to stop at its next step.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable

log = logging.getLogger("copilot.api")

# A job takes (on_progress, should_stop) and returns (event name, data).
Job = Callable[[Callable[[str], None], Callable[[], bool]], tuple[str, dict]]


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def run_as_stream(
    job: Job,
    keepalive_seconds: float,
    on_failure: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    """Yields the job's events as they happen.

    `on_failure` runs when the job raised, so whatever it had taken (a
    unit of quota) can be given back.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
    stop = threading.Event()

    def emit(item: tuple[str, dict] | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def work() -> None:
        try:
            emit(job(lambda stage: emit(("status", {"stage": stage})), stop.is_set))
        except Exception:  # noqa: BLE001 (any failure must reach the client as an error)
            log.exception("a pipeline run failed")
            if on_failure is not None:
                try:
                    on_failure()
                except Exception:  # noqa: BLE001
                    log.exception("could not undo after a failed run")
            emit(("error", {"message": "Something went wrong on our side. Please try again."}))
        finally:
            emit(None)

    worker = loop.run_in_executor(None, work)
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                yield ": still working\n\n"
                continue
            if item is None:
                break
            yield sse(*item)
    finally:
        # Reached when the run is over, and also when the client disconnects.
        # The worker then stops at its next step; nobody waits for it here.
        stop.set()
        del worker
