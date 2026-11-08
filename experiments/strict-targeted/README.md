# Strict targeted multi-pass benchmark

Run repeated sequential refactoring turns for the MCP-enabled agent against the
calculator fixture. The agent optimizes only expression-path count and keeps one
private copied workspace; the next turn starts from the previous accepted edit.

The ignored output directory preserves every turn's JSONL log, response, profile,
test result, and diff. Step 1 compares the original file with the first edit;
each later step compares the previous step with the current step.

The shared runner can execute this workflow directly, without importing the
experiment script. Prepare a copy of the fixture, then run it from the repository
root:

```sh
mkdir -p out/experiments/calculator
cp experiments/fixtures/calculator.py experiments/fixtures/test_calculator.py out/experiments/calculator/
uv run agent-runner run --depencity-eval \
  --repo out/experiments/calculator --target calculator.py --iterations 3 \
  --metric graph.paths.expressions.count \
  --test-command 'python -m pytest -q test_calculator.py -p no:cacheprovider' \
  --log-root /tmp/calculator-evaluations
```

The new command uses the normal Codex configuration and runs tests with the
supplied command. Configure Depencity MCP there if the agent should use it during
its search. The evaluator uses the local Depencity CLI independently.

The original script remains available for its ten-attempt prompt, Docker test
setup, and resume behavior:

```sh
uv run python experiments/strict-targeted/run.py --turns 3
```

The environment uses the editable `../depencity` package configured in the root
`pyproject.toml`. Run `uv sync` after updating that checkout.

The target metric is still `graph.paths.expressions.count`. The current profile
API returns aggregate values under `scopes[].profile` and direct values under
`own_profile`; `detail='compact'` is no longer supported. This experiment selects
`scope='__module__'` with `include_children=True`, `include_own_profile=True`, and
`metrics=['graph.paths.expressions.count']`. Acceptance compares the module's
aggregate value, including all descendants, and requires the calculator tests
to pass. Missing metrics raise an error rather than silently defaulting to zero.
