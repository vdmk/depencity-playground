"""Behavior tests for the calculator fixture."""

from __future__ import annotations

import pytest

from calculator import calculate


@pytest.mark.parametrize(
    ('expression', 'expected'),
    [
        ('2 + 3 * 4', 14),
        ('(2 + 3) * 4', 20),
        ('2 * (3 + (4 - 1))', 12),
        ('-2 * (+3)', -6),
        ('--4', 4),
        ('-(2 + 3)', -5),
        ('10 / 4', 2.5),
        ('0 * (1 + 2)', 0),
        ('0.5 + 1.25', 1.75),
        ('10 - 3 - 2', 5),
        ('20 / 5 / 2', 2),
        (' 12 + 3 ', 15),
    ],
)
def test_calculates_expression(expression: str, expected: int | float) -> None:
    assert calculate(expression) == expected


@pytest.mark.parametrize(
    'expression',
    ['', '()', '2 +', '2 + (3 * 4', '2 ** 3', '2 & 3', 'abc'],
)
def test_rejects_malformed_expression(expression: str) -> None:
    with pytest.raises(ValueError):
        calculate(expression)


def test_rejects_division_by_zero() -> None:
    with pytest.raises(ZeroDivisionError):
        calculate('1 / 0')
