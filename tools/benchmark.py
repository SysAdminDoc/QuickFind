"""Repeatable benchmark harness for QuickFind search and indexing performance.

Usage:
    python -m tools.benchmark                   # Run all benchmarks
    python -m tools.benchmark --export results  # Export JSON/CSV to results/
    python -m tools.benchmark --entries 500000  # Custom synthetic tree size

Builds a synthetic file tree in a temp directory, indexes it, and measures
cold/warm search, index build, and content search timings.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.index import FileEntry, FileIndex
from core.search import SearchEngine


@dataclass
class BenchmarkResult:
    name: str
    entries: int
    duration_ms: float
    ops_per_sec: float = 0.0
    notes: str = ""


@dataclass
class BenchmarkReport:
    timestamp: str = ""
    total_entries: int = 0
    results: list[BenchmarkResult] = field(default_factory=list)

    def add(self, result: BenchmarkResult) -> None:
        self.results.append(result)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_entries": self.total_entries,
            "results": [asdict(r) for r in self.results],
        }


def _synthetic_entries(count: int) -> list[FileEntry]:
    """Generate synthetic FileEntry objects for benchmarking."""
    entries = []
    extensions = [".txt", ".pdf", ".docx", ".py", ".jpg", ".png", ".zip", ".log", ".csv", ".json"]
    for i in range(count):
        ext = extensions[i % len(extensions)]
        name = f"file_{i:08d}{ext}"
        entry = FileEntry(
            frn=i + 100,
            parent_frn=5,
            name=name,
            drive="C",
            size=i * 17 % 10_000_000,
        )
        entry._path = f"C:\\bench\\dir_{i % 1000}\\{name}"
        entries.append(entry)
    return entries


def _build_index(entries: list[FileEntry]) -> tuple[FileIndex, SearchEngine]:
    """Build an in-memory index from synthetic entries."""
    index = FileIndex()
    index._entries = {"C": {}}
    from core.index import NTFS_ROOT_FRN
    from core.ntfs import FILE_ATTRIBUTE_DIRECTORY
    root = FileEntry(NTFS_ROOT_FRN, 0, "", "C", FILE_ATTRIBUTE_DIRECTORY)
    index._entries["C"][NTFS_ROOT_FRN] = root
    parent = FileEntry(5, NTFS_ROOT_FRN, "bench", "C", FILE_ATTRIBUTE_DIRECTORY)
    parent._path = "C:\\bench"
    index._entries["C"][5] = parent
    for entry in entries:
        index._entries["C"][entry.frn] = entry
    index._all_entries = list(entries)
    engine = SearchEngine(index)
    return index, engine


def _time_ms(fn: Callable[[], object]) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def run_benchmarks(entry_count: int = 100_000) -> BenchmarkReport:
    """Run the benchmark suite and return a report."""
    report = BenchmarkReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        total_entries=entry_count,
    )

    print(f"[*] Generating {entry_count:,} synthetic entries...")
    entries = []
    gen_ms = _time_ms(lambda: entries.extend(_synthetic_entries(entry_count)))
    report.add(BenchmarkResult("generate_entries", entry_count, gen_ms))

    print("[*] Building index...")
    index = engine = None

    def _build():
        nonlocal index, engine
        index, engine = _build_index(entries)

    build_ms = _time_ms(_build)
    report.add(BenchmarkResult(
        "build_index", entry_count, build_ms,
        ops_per_sec=entry_count / (build_ms / 1000) if build_ms > 0 else 0,
    ))

    queries = [
        ("simple_name", "file_00001"),
        ("wildcard_ext", "*.pdf"),
        ("substring", "0042"),
        ("no_match", "zzzznonexistent"),
    ]

    for label, query in queries:
        print(f"[*] Searching: {query}")
        results = []

        def _search():
            nonlocal results
            results = engine.search(query, max_results=1000)

        cold_ms = _time_ms(_search)
        cold_count = len(results)
        report.add(BenchmarkResult(
            f"search_cold_{label}", entry_count, cold_ms,
            notes=f"{cold_count} results",
        ))

        warm_ms = _time_ms(_search)
        report.add(BenchmarkResult(
            f"search_warm_{label}", entry_count, warm_ms,
            notes=f"{cold_count} results",
        ))

    iterations = 50
    total_ms = 0
    for _ in range(iterations):
        total_ms += _time_ms(lambda: engine.search("file_0000", max_results=100))
    avg_ms = total_ms / iterations
    report.add(BenchmarkResult(
        "search_avg_50x", entry_count, avg_ms,
        ops_per_sec=1000 / avg_ms if avg_ms > 0 else 0,
        notes="average over 50 iterations",
    ))

    return report


def format_report(report: BenchmarkReport) -> str:
    lines = [
        f"QuickFind Benchmark — {report.timestamp}",
        f"Entries: {report.total_entries:,}",
        "=" * 70,
    ]
    for r in report.results:
        ops = f"  ({r.ops_per_sec:,.0f} ops/s)" if r.ops_per_sec else ""
        notes = f"  [{r.notes}]" if r.notes else ""
        lines.append(f"  {r.name:<30s} {r.duration_ms:>10.2f} ms{ops}{notes}")
    return "\n".join(lines)


def export_report(report: BenchmarkReport, output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / "benchmark.json"
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"[+] JSON: {json_path}")

    csv_path = out / "benchmark.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "entries", "duration_ms", "ops_per_sec", "notes"])
        writer.writeheader()
        for r in report.results:
            writer.writerow(asdict(r))
    print(f"[+] CSV: {csv_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="QuickFind benchmark harness")
    parser.add_argument("--entries", type=int, default=100_000, help="Number of synthetic entries")
    parser.add_argument("--export", type=str, default="", help="Export JSON/CSV to this directory")
    args = parser.parse_args()

    report = run_benchmarks(args.entries)
    print(format_report(report))

    if args.export:
        export_report(report, args.export)


if __name__ == "__main__":
    main()
