"""In-process event broadcaster + the /events WS endpoint.

This is the `observer.py` four satellites carried as byte-identical copies
(transcript, people, body, head): emit() fans out to per-connection asyncio
queues; the JarvYZ-side generic event bridge (web/api/satellite_events.py)
tails the /events WS and re-broadcasts onto the core bus, so existing pubsub
consumers keep working unchanged."""
from __future__ import annotations

import asyncio
from typing import Any


class EventBroadcaster:
    """One per satellite, parameterized by core-bus channel name."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        """Register a new WS connection. Returns the queue it should
        `await q.get()` to receive events. Caller must `unsubscribe(q)` on
        disconnect."""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def emit(self, kind: str, **payload: Any) -> None:
        """Fan out one event to every connected WS subscriber.

        Frame shape `{event: <channel>, kind, ...payload}` matches the
        JarvYZ-bus convention so the core-side bridge can re-broadcast
        `kind=...` payloads as-is. asyncio.Queue is unbounded — keep it
        that way unless we see actual memory pressure."""
        msg = {"event": self.channel, "kind": kind, **payload}
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except Exception:
                pass

    def num_subscribers(self) -> int:
        return len(self._subscribers)


def make_events_router(broadcaster: EventBroadcaster):
    """The `/events` WebSocket endpoint as a mountable APIRouter: initial
    `hello` frame (so clients know the channel is live without waiting for
    the first mutation), then the queue pump. Lazy fastapi import keeps
    this wheel dependency-free."""
    from fastapi import APIRouter, WebSocket, WebSocketDisconnect

    router = APIRouter()

    @router.websocket("/events")
    async def events_ws(ws: WebSocket) -> None:
        await ws.accept()
        q = broadcaster.subscribe()
        try:
            await ws.send_json({"event": broadcaster.channel, "kind": "hello"})
            while True:
                msg = await q.get()
                await ws.send_json(msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            broadcaster.unsubscribe(q)

    return router
