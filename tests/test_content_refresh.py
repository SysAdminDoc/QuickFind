"""Tests for content-cache refresh queue driven by file-change events."""

from core.content.refresh_queue import (
    ChangeType,
    ContentRefreshItem,
    ContentRefreshQueue,
    enqueue_change,
    process_batch,
    should_refresh_content,
)


def test_enqueue_and_dequeue():
    q = ContentRefreshQueue(max_pending=100)
    item = ContentRefreshItem(path="C:\\a.txt", change=ChangeType.MODIFIED)
    assert q.enqueue(item)
    batch = q.dequeue_batch(10)
    assert len(batch) == 1
    assert batch[0].path == "C:\\a.txt"


def test_queue_capacity_limit():
    q = ContentRefreshQueue(max_pending=2)
    q.enqueue(ContentRefreshItem(path="a.txt", change=ChangeType.CREATED))
    q.enqueue(ContentRefreshItem(path="b.txt", change=ChangeType.CREATED))
    assert not q.enqueue(ContentRefreshItem(path="c.txt", change=ChangeType.CREATED))


def test_stats_track_pending():
    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path="a.txt", change=ChangeType.CREATED))
    q.enqueue(ContentRefreshItem(path="b.txt", change=ChangeType.MODIFIED))
    stats = q.stats()
    assert stats.pending == 2


def test_stats_track_processed_and_failed():
    q = ContentRefreshQueue()
    q.record_processed(5)
    q.record_failed(2)
    q.record_removed(1)
    stats = q.stats()
    assert stats.processed == 5
    assert stats.failed == 2
    assert stats.removed == 1


def test_clear_empties_queue():
    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path="a.txt", change=ChangeType.CREATED))
    q.enqueue(ContentRefreshItem(path="b.txt", change=ChangeType.CREATED))
    cleared = q.clear()
    assert cleared == 2
    assert q.stats().pending == 0


def test_should_refresh_content_matches_supported_extensions():
    assert should_refresh_content("report.pdf")
    assert should_refresh_content("notes.txt")
    assert should_refresh_content("main.py")
    assert not should_refresh_content("image.jpg")
    assert not should_refresh_content("video.mp4")


def test_should_refresh_with_custom_extensions():
    custom = frozenset({"jpg", "png"})
    assert should_refresh_content("photo.jpg", custom)
    assert not should_refresh_content("notes.txt", custom)


def test_enqueue_change_filters_unsupported_extensions():
    q = ContentRefreshQueue()
    assert enqueue_change(q, "photo.jpg", ChangeType.CREATED) is False
    assert q.stats().pending == 0


def test_enqueue_change_accepts_supported_extensions():
    q = ContentRefreshQueue()
    assert enqueue_change(q, "notes.txt", ChangeType.MODIFIED)
    assert q.stats().pending == 1


def test_enqueue_change_always_accepts_deletes():
    q = ContentRefreshQueue()
    assert enqueue_change(q, "photo.jpg", ChangeType.DELETED)
    assert q.stats().pending == 1


def test_process_batch_deletes(tmp_path):
    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path="C:\\gone.txt", change=ChangeType.DELETED))

    deleted = []
    process_batch(
        q,
        upsert_fn=lambda *a: None,
        delete_fn=lambda path: deleted.append(path),
        extract_fn=lambda path: "",
    )

    assert deleted == ["C:\\gone.txt"]
    stats = q.stats()
    assert stats.removed == 1


def test_process_batch_extracts_and_upserts(tmp_path):
    test_file = tmp_path / "doc.txt"
    test_file.write_text("secret content here", encoding="utf-8")

    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path=str(test_file), change=ChangeType.MODIFIED))

    upserted = []
    process_batch(
        q,
        upsert_fn=lambda *a: upserted.append(a),
        delete_fn=lambda path: None,
        extract_fn=lambda path: "extracted text",
    )

    assert len(upserted) == 1
    assert upserted[0][0] == str(test_file)
    assert upserted[0][4] == "extracted text"
    assert q.stats().processed == 1


def test_process_batch_handles_rename_deletes_old_path(tmp_path):
    new_file = tmp_path / "renamed.txt"
    new_file.write_text("content", encoding="utf-8")

    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(
        path=str(new_file),
        change=ChangeType.RENAMED,
        old_path="C:\\old_name.txt",
    ))

    deleted = []
    upserted = []
    process_batch(
        q,
        upsert_fn=lambda *a: upserted.append(a),
        delete_fn=lambda path: deleted.append(path),
        extract_fn=lambda path: "text",
    )

    assert "C:\\old_name.txt" in deleted
    assert len(upserted) == 1


def test_process_batch_records_failure_for_missing_file():
    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(
        path="C:\\nonexistent_file.txt",
        change=ChangeType.MODIFIED,
    ))

    process_batch(
        q,
        upsert_fn=lambda *a: None,
        delete_fn=lambda path: None,
        extract_fn=lambda path: "",
    )

    assert q.stats().failed == 1


def test_stale_snippet_disappears_after_delete(tmp_path):
    cache = {}

    def upsert(path, size, modified_ms, extractor, text):
        cache[path] = text

    def delete(path):
        cache.pop(path, None)

    test_file = tmp_path / "secret.txt"
    test_file.write_text("sensitive SSN data", encoding="utf-8")
    path_str = str(test_file)

    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path=path_str, change=ChangeType.CREATED))
    process_batch(q, upsert, delete, lambda p: "sensitive SSN data")
    assert path_str in cache

    q.enqueue(ContentRefreshItem(path=path_str, change=ChangeType.DELETED))
    process_batch(q, upsert, delete, lambda p: "")
    assert path_str not in cache


def test_empty_extraction_counts_as_failure(tmp_path):
    test_file = tmp_path / "empty.txt"
    test_file.write_text("", encoding="utf-8")

    q = ContentRefreshQueue()
    q.enqueue(ContentRefreshItem(path=str(test_file), change=ChangeType.MODIFIED))

    upserted = []
    process_batch(
        q,
        upsert_fn=lambda *a: upserted.append(a),
        delete_fn=lambda path: None,
        extract_fn=lambda path: "",
    )

    assert len(upserted) == 0
    assert q.stats().failed == 1
