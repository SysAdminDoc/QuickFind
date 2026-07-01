"""Bounded content-cache refresh queue driven by file-change events."""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

logger = logging.getLogger("QuickFind.ContentRefresh")


class ChangeType(Enum):
    CREATED = auto()
    MODIFIED = auto()
    RENAMED = auto()
    DELETED = auto()


@dataclass(frozen=True)
class ContentRefreshItem:
    path: str
    change: ChangeType
    old_path: str = ""


@dataclass
class RefreshQueueStats:
    pending: int = 0
    processed: int = 0
    failed: int = 0
    removed: int = 0


class ContentRefreshQueue:
    """Thread-safe bounded queue for content-cache refresh work."""

    def __init__(self, max_pending: int = 10_000):
        self._lock = threading.Lock()
        self._queue: deque[ContentRefreshItem] = deque(maxlen=max_pending)
        self._processed = 0
        self._failed = 0
        self._removed = 0

    def enqueue(self, item: ContentRefreshItem) -> bool:
        """Add an item to the queue. Returns False if at capacity."""
        with self._lock:
            if len(self._queue) >= self._queue.maxlen:
                return False
            self._queue.append(item)
            return True

    def dequeue_batch(self, max_items: int = 100) -> list[ContentRefreshItem]:
        """Remove up to max_items from the queue."""
        with self._lock:
            batch = []
            for _ in range(min(max_items, len(self._queue))):
                batch.append(self._queue.popleft())
            return batch

    def record_processed(self, count: int = 1) -> None:
        with self._lock:
            self._processed += count

    def record_failed(self, count: int = 1) -> None:
        with self._lock:
            self._failed += count

    def record_removed(self, count: int = 1) -> None:
        with self._lock:
            self._removed += count

    def stats(self) -> RefreshQueueStats:
        with self._lock:
            return RefreshQueueStats(
                pending=len(self._queue),
                processed=self._processed,
                failed=self._failed,
                removed=self._removed,
            )

    def clear(self) -> int:
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count


SUPPORTED_CONTENT_REFRESH_EXTENSIONS = frozenset({
    "txt", "md", "csv", "log", "json", "xml", "yaml", "yml",
    "pdf", "docx", "pptx", "py", "js", "ts", "html", "htm",
    "c", "cpp", "h", "cs", "java", "rs", "go", "rb", "sh",
    "bat", "ps1", "cfg", "ini", "toml",
})


def should_refresh_content(path: str, extensions: frozenset[str] | None = None) -> bool:
    """Check if a path is eligible for content refresh."""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    allowed = extensions or SUPPORTED_CONTENT_REFRESH_EXTENSIONS
    return ext in allowed


def enqueue_change(
    queue: ContentRefreshQueue,
    path: str,
    change: ChangeType,
    old_path: str = "",
    extensions: frozenset[str] | None = None,
) -> bool:
    """Enqueue a content refresh if the path is eligible."""
    if change == ChangeType.DELETED:
        return queue.enqueue(ContentRefreshItem(path=path, change=change))

    if not should_refresh_content(path, extensions):
        return False

    return queue.enqueue(ContentRefreshItem(
        path=path, change=change, old_path=old_path,
    ))


def process_batch(
    queue: ContentRefreshQueue,
    upsert_fn,
    delete_fn,
    extract_fn,
    max_items: int = 50,
) -> int:
    """Process a batch of refresh items. Returns count processed."""
    batch = queue.dequeue_batch(max_items)
    if not batch:
        return 0

    processed = 0
    for item in batch:
        try:
            if item.change == ChangeType.DELETED:
                delete_fn(item.path)
                queue.record_removed()
                processed += 1
                continue

            if item.change == ChangeType.RENAMED and item.old_path:
                delete_fn(item.old_path)
                queue.record_removed()

            if not os.path.exists(item.path):
                queue.record_failed()
                continue

            text = extract_fn(item.path)
            if text:
                stat = os.stat(item.path)
                upsert_fn(
                    item.path,
                    int(stat.st_size),
                    int(stat.st_mtime * 1000),
                    "refresh",
                    text,
                )
            processed += 1
            queue.record_processed()
        except Exception as e:
            logger.debug("Content refresh failed for %s: %s", item.path, e)
            queue.record_failed()

    return processed
