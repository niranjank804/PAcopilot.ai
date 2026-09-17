"""Heartbeats on a quiet stream.

A tool-using answer can go silent for most of a minute. The reported
symptom was half an answer on screen and nothing more, while the full
answer sat saved on the server: a quiet connection had been treated as a
dead one somewhere between the two.
"""

import asyncio

import pytest

from src.core.sse import HEARTBEAT, with_heartbeat


async def _collect(stream):
    return [item async for item in stream]


@pytest.mark.asyncio
async def test_a_quiet_gap_is_filled_with_heartbeats():
    async def slow():
        yield "data: first\n\n"
        await asyncio.sleep(0.25)
        yield "data: second\n\n"

    items = await _collect(with_heartbeat(slow(), interval=0.05))

    assert items[0] == "data: first\n\n"
    assert items[-1] == "data: second\n\n"
    assert HEARTBEAT in items[1:-1]


@pytest.mark.asyncio
async def test_a_busy_stream_is_passed_through_untouched():
    async def fast():
        for index in range(5):
            yield f"data: {index}\n\n"

    items = await _collect(with_heartbeat(fast(), interval=5))

    assert items == [f"data: {index}\n\n" for index in range(5)]


@pytest.mark.asyncio
async def test_heartbeats_are_sse_comments_every_client_ignores():
    assert HEARTBEAT.startswith(":")
    assert HEARTBEAT.endswith("\n\n")


@pytest.mark.asyncio
async def test_a_failure_in_the_source_still_reaches_the_caller():
    async def broken():
        yield "data: ok\n\n"
        raise RuntimeError("provider exploded")

    stream = with_heartbeat(broken(), interval=5)

    assert await stream.__anext__() == "data: ok\n\n"
    with pytest.raises(RuntimeError, match="provider exploded"):
        await stream.__anext__()


@pytest.mark.asyncio
async def test_closing_the_stream_stops_the_work_behind_it():
    cancelled = asyncio.Event()

    async def endless():
        try:
            while True:
                yield "data: tick\n\n"
                await asyncio.sleep(0.01)
        finally:
            cancelled.set()

    stream = with_heartbeat(endless(), interval=5)
    await stream.__anext__()
    # What Starlette does when the browser disconnects.
    await stream.aclose()

    await asyncio.wait_for(cancelled.wait(), timeout=1)
