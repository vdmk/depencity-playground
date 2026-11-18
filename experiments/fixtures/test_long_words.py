"""Behavior contract for refactoring the two-loop example."""

import pytest

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
