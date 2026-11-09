# Strict targeted calculator experiment

```sh
uv run agent-runner run-experiment \
  --repo experiments/fixtures --target calculator.py --test-script test_calculator.py \
  --iterations 3 --metric graph.paths.expressions.count \
  --task "$(cat experiments/strict-targeted/task.md)" \
  --log-root "$PWD/out/experiments/strict-targeted"
```

The runner copies the target and test file into its run directory. Originals stay
untouched; logs, diffs, measurements, and accepted snapshots are saved alongside
each variant's files in `plain/` and `depencity/`. Both variants run in parallel.
Both workers receive the same Markdown prompt; only tool availability differs.
The evaluator restores the original tests before Docker validation.
Repeat the command with `--continue` to resume the latest run; `--iterations`
sets the total per variant, including completed iterations.
Add `--accept-improvements-only` to accept only candidates with passing tests
and lower metric values. Rejected candidates are logged, then rolled back before
the next iteration. The flag can also be enabled with `--continue`; previous
iterations are not re-evaluated.

Run `uv sync` after updating `../depencity`. Workers use the runner's explicit MCP
configuration; evaluation uses the Depencity CLI and Docker tests.
