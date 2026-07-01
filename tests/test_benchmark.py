"""Tests for the benchmark harness."""

import json
from pathlib import Path

from tools.benchmark import (
    BenchmarkReport,
    BenchmarkResult,
    _build_index,
    _synthetic_entries,
    export_report,
    format_report,
    run_benchmarks,
)


def test_synthetic_entries_generates_correct_count():
    entries = _synthetic_entries(500)
    assert len(entries) == 500
    assert entries[0].name.startswith("file_")
    assert entries[0].name.endswith(".txt")


def test_synthetic_entries_cover_multiple_extensions():
    entries = _synthetic_entries(20)
    extensions = {e.name.rsplit(".", 1)[-1] for e in entries}
    assert len(extensions) >= 5


def test_build_index_populates_all_entries():
    entries = _synthetic_entries(100)
    index, engine = _build_index(entries)
    assert len(index.all_entries) == 100
    assert index._entries["C"][entries[0].frn] is entries[0]


def test_run_benchmarks_returns_report():
    report = run_benchmarks(entry_count=500)
    assert report.total_entries == 500
    assert len(report.results) >= 5
    assert all(r.duration_ms >= 0 for r in report.results)


def test_format_report_includes_timings():
    report = BenchmarkReport(
        timestamp="2026-07-01T00:00:00",
        total_entries=100,
        results=[BenchmarkResult("test_op", 100, 12.5, 8000, "ok")],
    )
    text = format_report(report)
    assert "test_op" in text
    assert "12.50" in text
    assert "8,000" in text


def test_export_report_writes_json_and_csv(tmp_path):
    report = BenchmarkReport(
        timestamp="2026-07-01T00:00:00",
        total_entries=100,
        results=[BenchmarkResult("test_op", 100, 5.0)],
    )
    export_report(report, str(tmp_path))

    json_path = tmp_path / "benchmark.json"
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["total_entries"] == 100
    assert len(data["results"]) == 1

    csv_path = tmp_path / "benchmark.csv"
    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert "test_op" in lines[1]
