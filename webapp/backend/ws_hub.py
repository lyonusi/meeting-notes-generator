"""WebSocketHub: client tracking, event broadcast, and on-connect replay.

This module implements the :class:`WebSocketHub` described in the design's
"Components" section (Task 10.1). The hub is the fan-out point for everything the
backend pushes to browser clients over ``/ws/captions``:

- It tracks connected clients (FastAPI/Starlette ``WebSocket`` objects, typed
  loosely as ``Any`` so this module has no hard import coupling to the web
  framework).
- It broadcasts the typed event envelope ``{type, seq, payload}`` (Req 1.3, 4.4,
  2.6, 1.8, 2.3, 2.5, 2.8, 2.2, 5.8, 5.6) with a monotonically increasing
  ``seq``. ``broadcast`` matches the tiny ``broadcast(event_type, payload)``
  interface :class:`~webapp.backend.session_manager.RecordingSessionManager`
  expects of its sink, so the manager can emit caption/status/error events
  through it directly.
- On (re)connect it first replays the ascending-``start`` caption snapshot, then
  streams subsequent live events, so a freshly (re)connected client never misses
  a caption (Req 1.6).

Thread/async bridging (the important bit)
-----------------------------------------

The session manager's caption poll loop (Task 8.1) runs in a **worker thread**
and calls :meth:`broadcast` synchronously, while each client is serviced by an
``async`` coroutine running on the event loop. The hub bridges the two with a
**per-client** :class:`asyncio.Queue` drained by an async sender:

- At :meth:`connect` time the hub captures the running event loop and creates a
  queue for that client.
- :meth:`broadcast` (callable from *any* thread) builds one envelope and, for
  each client, schedules a non-blocking ``queue.put_nowait`` onto that client's
  loop via :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`. It never
  blocks the caller and never touches a ``WebSocket`` from the worker thread.
- The async :meth:`connect` coroutine sends the caption snapshot directly, then
  drains the queue forever, awaiting ``ws.send_json`` for each envelope. Because
  the client is registered *before* the snapshot is sent, any concurrent live
  event is enqueued and delivered *after* the snapshot (Req 1.6); same-``start``
  duplicates are harmless because the client de-duplicates captions by ``start``.

Send failures and disconnects are swallowed: the offending client is dropped and
the broadcast loop keeps running for everyone else.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


#: Sentinel pushed onto a client queue to make its drain coroutine exit cleanly.
_CLOSE = object()


class _Client:
    """Per-connection state: the socket, its event loop, and its send queue."""

    __slots__ = ("ws", "loop", "queue")

    def __init__(
        self,
        ws: Any,
        loop: asyncio.AbstractEventLoop,
        queue: "asyncio.Queue[Any]",
    ) -> None:
        self.ws = ws
        self.loop = loop
        self.queue = queue


class WebSocketHub:
    """Tracks WebSocket clients, broadcasts typed events, and replays on connect.

    The hub is intentionally decoupled from
    :class:`~webapp.backend.session_manager.RecordingSessionManager`: the manager
    holds a reference to the hub as its ``broadcaster`` and calls
    ``broadcast(event_type, payload)``; the hub pulls the replay snapshot from an
    injected provider (or one set later via :meth:`set_snapshot_provider`) so it
    never imports the manager.

    Args:
        snapshot_provider: Optional zero-arg callable returning the captions to
            replay on connect, already ascending by ``start`` (the manager's
            :meth:`RecordingSessionManager.captions_snapshot`). When omitted, no
            captions are replayed until a provider is set.
    """

    def __init__(
        self,
        snapshot_provider: Optional[Callable[[], List[Any]]] = None,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        # Guards the client set and the seq counter; broadcast runs from worker
        # threads, connect/disconnect from the event loop, so a lock is required.
        self._lock = threading.Lock()
        self._clients: set[_Client] = set()
        self._seq = itertools.count()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_snapshot_provider(
        self, provider: Optional[Callable[[], List[Any]]]
    ) -> None:
        """Set/replace the callable used to fetch the on-connect replay snapshot."""
        self._snapshot_provider = provider

    def client_count(self) -> int:
        """Return the number of currently registered clients."""
        with self._lock:
            return len(self._clients)

    # ------------------------------------------------------------------
    # Connection lifecycle (async; runs on the event loop)
    # ------------------------------------------------------------------

    async def connect(self, ws: Any) -> None:
        """Accept ``ws``, replay the caption snapshot, then stream live events.

        Blocks for the lifetime of the connection, draining the client's queue
        and writing each envelope to the socket. Returns when the socket closes
        or a send fails; the client is always unregistered on the way out.

        Order guarantee (Req 1.6): the client is registered *before* the snapshot
        is sent, so live events produced during connect are queued and delivered
        only after the full ascending-``start`` snapshot.
        """
        await ws.accept()
        loop = asyncio.get_running_loop()
        queue: "asyncio.Queue[Any]" = asyncio.Queue()
        client = _Client(ws, loop, queue)

        with self._lock:
            self._clients.add(client)

        try:
            # 1) Replay everything produced before this (re)connect, in order.
            for caption in self._current_snapshot():
                await ws.send_json(self._caption_envelope(caption))

            # 2) Stream subsequent live events from the queue.
            while True:
                item = await queue.get()
                if item is _CLOSE:
                    break
                await ws.send_json(item)
        except Exception:  # pragma: no cover - network/socket errors are expected
            logger.debug("WebSocket client send loop ended", exc_info=True)
        finally:
            self._remove(client)

    async def disconnect(self, ws: Any) -> None:
        """Unregister ``ws`` and wake its drain loop so :meth:`connect` returns."""
        target: Optional[_Client] = None
        with self._lock:
            for client in self._clients:
                if client.ws is ws:
                    target = client
                    break
        if target is not None:
            self._remove(target)
            try:
                target.queue.put_nowait(_CLOSE)
            except Exception:  # pragma: no cover - queue may already be gone
                pass

    # ------------------------------------------------------------------
    # Broadcast (sync; safe to call from any thread)
    # ------------------------------------------------------------------

    def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Send ``{type, seq, payload}`` to every connected client.

        This is the sink interface
        :class:`~webapp.backend.session_manager.RecordingSessionManager` expects.
        It is **thread-safe** and non-blocking: the envelope is enqueued onto each
        client's loop via ``call_soon_threadsafe`` and the actual ``send_json``
        happens in the client's async drain loop. Dead/closed clients are dropped
        without disturbing the others.
        """
        with self._lock:
            seq = next(self._seq)
            clients = list(self._clients)

        envelope = {"type": event_type, "seq": seq, "payload": payload}
        for client in clients:
            self._enqueue(client, envelope)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enqueue(self, client: _Client, envelope: Dict[str, Any]) -> None:
        """Schedule ``envelope`` onto ``client``'s loop; drop the client on error."""
        try:
            client.loop.call_soon_threadsafe(client.queue.put_nowait, envelope)
        except RuntimeError:
            # Loop is closed/closing - the client is gone.
            self._remove(client)
        except Exception:  # pragma: no cover - defensive
            logger.debug("Failed to enqueue event for a client", exc_info=True)
            self._remove(client)

    def _remove(self, client: _Client) -> None:
        """Idempotently unregister a client."""
        with self._lock:
            self._clients.discard(client)

    def _current_snapshot(self) -> List[Any]:
        """Return the replay snapshot from the provider (empty if none/raises)."""
        provider = self._snapshot_provider
        if provider is None:
            return []
        try:
            return list(provider())
        except Exception:  # pragma: no cover - provider is best-effort
            logger.exception("snapshot_provider failed; replaying no captions")
            return []

    @staticmethod
    def _caption_envelope(caption: Any) -> Dict[str, Any]:
        """Build a ``caption`` event envelope for a replayed caption.

        Replayed captions are sent without a live ``seq`` (``seq`` is ``None``)
        so a reconnecting client can tell snapshot frames from live ones; the
        payload matches the live ``caption`` shape ``{text, start, end, status}``.
        """
        return {
            "type": "caption",
            "seq": None,
            "payload": {
                "text": caption.text,
                "start": caption.start,
                "end": caption.end,
                "status": caption.status,
            },
        }


__all__ = ["WebSocketHub"]
