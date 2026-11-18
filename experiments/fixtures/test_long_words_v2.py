"""Original behavior contract plus a heavy pytest-benchmark test."""

import pytest
import memray
from pathlib import Path
from tempfile import TemporaryDirectory

from long_words import long_words


@pytest.mark.parametrize(("sentence", "expected"), [
    ("", []),
    (" \t\n ", []),
    ("hello", []),
    ("cat dog fox", []),
    ("a bb ccc", ["ccc"]),
    ("the curious cat sleeps", ["curious", "sleeps"]),
    ("an elephant elephant", ["elephant", "elephant"]),
    ("  a\tlonger\nword  ", ["longer", "word"]),
    ("hi there!", ["there!"]),
    ("é 猫猫 abc", ["abc"]),
])
def test_long_words(sentence, expected):
    assert long_words(sentence) == expected


def test_heavy(benchmark):
    sentence = "an elephant " * 32_000
    result = benchmark(long_words, sentence)
    assert result == ["elephant"] * 32_000


def test_memory(request):
    sentence = "an elephant " * 32_000
    with TemporaryDirectory() as directory:
        capture = Path(directory) / "memory.bin"
        with memray.Tracker(capture, trace_python_allocators=True):
            result = long_words(sentence)
        records = list(memray.FileReader(capture).get_high_watermark_allocation_records())
    assert result == ["elephant"] * 32_000
    peak = sum(record.size for record in records)
    allocations = sum(record.n_allocations for record in records)
    terminal = request.config.pluginmanager.get_plugin("terminalreporter")
    terminal.write_sep("-", "memory: long_words")
    terminal.write_line(f"{'Test':<20} {'Peak bytes':>14} {'Allocations at peak':>22}")
    terminal.write_line(f"{'test_memory':<20} {peak:>14,} {allocations:>22,}")
