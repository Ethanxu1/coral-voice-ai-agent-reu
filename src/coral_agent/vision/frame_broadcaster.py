import asyncio
from typing import Optional


class FrameBroadcaster:
    """Thread-safe broadcaster: one sync producer, N async consumers."""

    def __init__(self, loop: asyncio.AbstractEventLoop, capacity: int = 2):
        self._loop = loop
        self._capacity = capacity
        self._pose_queues: list[asyncio.Queue] = []
        self._video_queues: list[asyncio.Queue] = []

    def subscribe_pose(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._capacity)
        self._pose_queues.append(q)
        return q

    def unsubscribe_pose(self, q: asyncio.Queue):
        self._pose_queues = [x for x in self._pose_queues if x is not q]

    def subscribe_video(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._capacity)
        self._video_queues.append(q)
        return q

    def unsubscribe_video(self, q: asyncio.Queue):
        self._video_queues = [x for x in self._video_queues if x is not q]

    def _safe_put(self, q: asyncio.Queue, item):
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def publish_pose(self, data: dict):
        """Called from sync vision thread."""
        for q in list(self._pose_queues):
            self._loop.call_soon_threadsafe(self._safe_put, q, data)

    def publish_video(self, jpeg_bytes: bytes):
        """Called from sync vision thread."""
        for q in list(self._video_queues):
            self._loop.call_soon_threadsafe(self._safe_put, q, jpeg_bytes)
