import asyncio
import threading
import time

from copilot.api.streaming import run_as_stream, sse


async def collect(stream):
    return [item async for item in stream]


def test_events_come_in_order_and_end_with_the_result():
    def job(progress, should_stop):
        progress("understanding")
        progress("writing")
        return "result", {"code": "Buy = 1;"}

    items = asyncio.run(collect(run_as_stream(job, keepalive_seconds=5)))
    assert items == [
        sse("status", {"stage": "understanding"}),
        sse("status", {"stage": "writing"}),
        sse("result", {"code": "Buy = 1;"}),
    ]


def test_a_comment_keeps_the_stream_open_while_waiting():
    def job(progress, should_stop):
        time.sleep(0.35)
        return "result", {}

    items = asyncio.run(collect(run_as_stream(job, keepalive_seconds=0.1)))
    assert items[0] == ": still working\n\n"
    assert items[-1] == sse("result", {})


def test_a_failing_job_gives_an_error_event_and_undoes():
    undone = []

    def job(progress, should_stop):
        raise RuntimeError("database went away")

    items = asyncio.run(collect(run_as_stream(job, 5, on_failure=lambda: undone.append(1))))
    assert items == [
        sse("error", {"message": "Something went wrong on our side. Please try again."})
    ]
    assert undone == [1]
    assert "database" not in items[0]


def test_when_the_client_leaves_the_job_is_told_to_stop():
    stopped = threading.Event()
    started = threading.Event()

    def job(progress, should_stop):
        progress("understanding")
        started.set()
        for _ in range(200):
            if should_stop():
                stopped.set()
                return "cancelled", {}
            time.sleep(0.01)
        return "result", {}

    async def leave_early():
        stream = run_as_stream(job, keepalive_seconds=5)
        first = await stream.__anext__()
        await stream.aclose()
        return first

    first = asyncio.run(leave_early())
    assert first == sse("status", {"stage": "understanding"})
    assert stopped.wait(2)


def test_event_format():
    assert sse("status", {"stage": "checking"}) == 'event: status\ndata: {"stage": "checking"}\n\n'
