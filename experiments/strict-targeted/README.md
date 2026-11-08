# Strict targeted multi-pass benchmark

Run repeated sequential refactoring turns for the MCP-enabled agent against the
calculator fixture. The agent optimizes only expression-path count and keeps one
private copied workspace; the next turn starts from the previous accepted edit.

The ignored output directory preserves every turn's JSONL log, response, profile,
test result, and diff. Step 1 compares the original file with the first edit;
each later step compares the previous step with the current step.

Run it from the repository root:

```bash
uv run python experiments/strict-targeted/run.py
```

The default is three turns. Pass `--turns N` to run a different number.


The environment uses the editable `../depencity` package configured in the root
`pyproject.toml`. Run `uv sync` after updating that checkout.

The target metric is still `graph.paths.expressions.count`. The current profile
API returns aggregate values under `scopes[].profile` and direct values under
`own_profile`; `detail='compact'` is no longer supported. This experiment selects
`scope='__module__'` with `include_children=True`, `include_own_profile=True`, and
`metrics=['graph.paths.expressions.count']`. Acceptance compares the module's
aggregate value, including all descendants, and requires the calculator tests
to pass. Missing metrics raise an error rather than silently defaulting to zero.
