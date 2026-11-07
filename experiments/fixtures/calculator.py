"""Evaluate arithmetic expressions containing numbers, operators, and parentheses."""

from __future__ import annotations

import re
import sys


TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d+)?)|(.))')


def calculate(expression: str) -> int | float:
    """Return the value of an expression using standard operator precedence."""
    tokens = _tokenize(expression)
    position = 0

    def parse_expression() -> float:
        nonlocal position
        value = parse_term()
        while position < len(tokens) and tokens[position] in ('+', '-'):
            operator = tokens[position]
            position += 1
            right = parse_term()
            value = value + right if operator == '+' else value - right
        return value

    def parse_term() -> float:
        nonlocal position
        value = parse_factor()
        while position < len(tokens) and tokens[position] in ('*', '/'):
            operator = tokens[position]
            position += 1
            right = parse_factor()
            if operator == '*':
                value *= right
            else:
                value /= right
        return value

    def parse_factor() -> float:
        nonlocal position
        if position >= len(tokens):
            raise ValueError('expected a number or parenthesized expression')
        token = tokens[position]
        if token in ('+', '-'):
            position += 1
            value = parse_factor()
            return value if token == '+' else -value
        if token == '(':
            position += 1
            value = parse_expression()
            if position >= len(tokens) or tokens[position] != ')':
                raise ValueError('missing closing parenthesis')
            position += 1
            return value
        if token == ')' or not token[0].isdigit():
            raise ValueError(f'unexpected token: {token}')
        position += 1
        return float(token)

    result = parse_expression()
    if position != len(tokens):
        raise ValueError(f'unexpected token: {tokens[position]}')
    return int(result) if result.is_integer() else result


def _tokenize(expression: str) -> list[str]:
    expression = expression.strip()
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = TOKEN.match(expression, position)
        if match is None:
            raise ValueError(f'invalid character at position {position}')
        number, symbol = match.groups()
        tokens.append(number or symbol)
        position = match.end()
    return tokens


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f'usage: {sys.argv[0]} EXPRESSION')
    print(calculate(sys.argv[1]))


if __name__ == '__main__':
    main()
