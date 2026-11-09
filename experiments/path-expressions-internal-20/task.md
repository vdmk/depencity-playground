Refactor calculator.py make less dependencies across values and functions. Eliminate unnecessary things, simplify.


Make 20 attempts. For each attempt:
- Simplify.
- Run test_calculator.py in docker mcp. If tests don't pass fix.
- Asses dependency complexity across expressions.
- If complexity growths - rollback.
- Next iteration.