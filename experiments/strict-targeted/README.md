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
