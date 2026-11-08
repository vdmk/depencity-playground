# Strict targeted calculator experiment

```sh
uv run agent-runner run --depencity-eval \
  --repo experiments/fixtures --target calculator.py --test-script test_calculator.py \
  --iterations 3 --metric graph.paths.expressions.count \
  --task "$(cat experiments/strict-targeted/task.md)" \
  --log-root "$PWD/out/experiments/strict-targeted"
```

The runner copies the target and test file into its run directory. Originals stay
untouched; logs, diffs, measurements, and accepted snapshots are saved alongside
the workspace. The prompt in `task.md` requests only the expression-path metric
and requires internal attempts until a tested strict improvement is found.

Run `uv sync` after updating `../depencity`. The agent uses normal Codex
configuration; evaluation uses the Depencity CLI and pytest.
