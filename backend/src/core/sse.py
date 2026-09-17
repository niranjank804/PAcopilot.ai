"""Server-Sent Events helpers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress

# An SSE comment line: every client ignores it, and it is still bytes on
# the wire.
HEARTBEAT = ": keep-alive\n\n"

_END = object()


class _Failure:
    def __init__(self, exc: Exception):
        self.exc = exc


async def with_heartbeat(
    events: AsyncIterator[str],
    interval: float,
) -> AsyncIterator[str]:
    """Pass `events` through, sending a heartbeat after each quiet `interval`.

    A tool-using answer goes silent for long stretches: while the model
    thinks, while a TM1 call runs, before the final answer starts. Nothing
    crosses the connection in that time, so any proxy with an idle timeout
    is free to close it — and the browser, seeing the stream simply end,
    shows half an answer with nothing to say the rest was lost.

    The source is consumed by one background task rather than by a fresh
    task per item, because the provider's HTTP stream is entered in the
    task that first iterates it and must be finished in that same task.
    """

    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            async for item in events:
                await queue.put(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # re-raised on the consuming side
            await queue.put(_Failure(exc))
        else:
            await queue.put(_END)

    producer = asyncio.create_task(produce())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield HEARTBEAT
                continue

            if item is _END:
                return

            if isinstance(item, _Failure):
                raise item.exc

            yield item
    finally:
        # The client went away (or the stream failed): stop the work rather
        # than leave it running with nobody to send it to.
        if not producer.done():
            producer.cancel()

            with suppress(asyncio.CancelledError):
                await producer
