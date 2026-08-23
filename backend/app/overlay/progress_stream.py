"""Bridges compute_overlay's synchronous `on_progress` callback out to a
real Server-Sent Events (SSE) response, for POST /api/overlay/compute/
stream — genuine incremental progress, not a fabricated/animated
progress bar: every message the frontend sees was actually emitted from
inside compute_overlay as it did the real work.

Why a background thread + queue, not just yielding directly: compute_
overlay is a single blocking call (resolving each criterion is real,
possibly slow, synchronous I/O) — a plain Python generator has no way to
yield a value from a callback several calls deep inside a nested,
already-executing call frame. Running compute_overlay in its own thread
(pushing progress messages onto a thread-safe queue.Queue as it goes)
while THIS function's own generator polls that queue and yields each
message as it arrives is the standard way to bridge synchronous,
callback-driven progress into a streamable sequence. The router's route
handler itself is already a plain (non-async) `def`, which FastAPI runs
in its own worker thread automatically (same as every other route in
this module) — no asyncio-level bridging needed on top of that.
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator

from app.data.aoi import AOI
from app.data.errors import DataSourceUnavailableError, NodataValidationError, ReclassificationError

from .errors import OverlayValidationError
from .models import OverlayComputeResponse
from .service import OverlayCriterionRequest, compute_overlay

# Errors compute_overlay/its callees are documented to raise for a bad
# request or an unavailable data source -- the same set POST /compute's
# own (non-streaming) handler catches and translates to a 4xx/5xx. An SSE
# response's HTTP status is already 200 by the time streaming starts, so
# these can't become HTTP status codes here the way they do there; they
# become an in-band "error" event instead (see _stream_compute_events).
_KNOWN_ERROR_TYPES = (
    OverlayValidationError,
    NodataValidationError,
    ReclassificationError,
    DataSourceUnavailableError,
)


def _sse_line(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload})}\n\n"


def stream_compute_events(
    aoi: AOI, criteria: list[OverlayCriterionRequest], final_weights: dict[str, float], complete: bool
) -> Iterator[str]:
    """Yields SSE `data:` lines: zero or more `{"type": "progress",
    "message": str}`, followed by exactly one terminal event —
    `{"type": "done", "result": <same shape POST /compute returns>}` on
    success, or `{"type": "error", "error": str, "message": str}` if
    compute_overlay raised one of the known error types above (any other
    exception is re-raised in the worker thread and surfaces here as a
    generic "internal_error", never silently swallowed).
    """
    events: queue.Queue = queue.Queue()
    DONE = object()  # sentinel distinguishing "a real message" from "the queue is closed"

    def worker() -> None:
        try:
            result = compute_overlay(aoi, criteria, final_weights, complete, on_progress=events.put)
            events.put(("done", result))
        except _KNOWN_ERROR_TYPES as exc:
            error_type = {
                OverlayValidationError: "overlay_validation_error",
                NodataValidationError: "overlay_data_error",
                ReclassificationError: "overlay_data_error",
                DataSourceUnavailableError: "data_source_unavailable",
            }[type(exc)]
            events.put(("error", error_type, str(exc)))
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: must still reach the client, not vanish
            events.put(("error", "internal_error", str(exc)))
        finally:
            events.put(DONE)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        item = events.get()
        if item is DONE:
            break
        if isinstance(item, str):
            yield _sse_line("progress", {"message": item})
        elif item[0] == "done":
            response = OverlayComputeResponse.from_overlay_result(item[1])
            yield _sse_line("done", {"result": response.model_dump()})
        elif item[0] == "error":
            yield _sse_line("error", {"error": item[1], "message": item[2]})

    thread.join()
