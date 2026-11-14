"""Behavior contract for the text-table experiment."""

import pytest

from text_table import format_table


@pytest.mark.parametrize(("rows", "headers", "expected"), [
    ([], None, ""),
    ([[], []], None, ""),
    ([], [], ""),
    ([["a", 12], ["long", 3]], None, "a    | 12\nlong | 3"),
    ([["Ada", 7]], ["Name", "Score"], "Name | Score\n-----+------\nAda  | 7"),
    ([], ["Name", "Age"], "Name | Age\n-----+----"),
    ([["a"], ["bb", "c"]], None, "a  |\nbb | c"),
    ([[None, False, 0]], None, "None | False | 0"),
    ([["a\nb", "x"], ["c", "y\nz"]], None, "a | x\nb |\nc | y\n  | z"),
    ([["x\n", "y"]], None, "x | y\n  |"),
    ([["é", "猫"]], None, "é | 猫"),
    ([[" a ", "b "]], None, " a  | b"),
    ([["a", "b"]], ["H"], "H |\n--+--\na | b"),
    ([["v"]], ["A\nB"], "A\nB\n-\nv"),
    ([["", ""]], None, " |"),
])
def test_formats_table(rows, headers, expected):
    assert format_table(rows, headers) == expected


def test_accepts_iterables_without_mutating_inputs():
    rows = [["a"], ["bb", 2]]
    headers = ["Name", "Count"]
    assert format_table((iter(row) for row in rows), iter(headers)) == (
        "Name | Count\n-----+------\na    |\nbb   | 2"
    )
    assert rows == [["a"], ["bb", 2]]
    assert headers == ["Name", "Count"]
