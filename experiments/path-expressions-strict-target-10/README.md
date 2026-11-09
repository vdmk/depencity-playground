# Expression-path search, 10 internal attempts

Run 20 outer turns with Luna and Depencity only:

```sh
uv run agent-runner run --depencity-eval \
  --repo experiments/fixtures --target calculator.py --test-script test_calculator.py \
  --model gpt-6-luna --iterations 20 --metric graph.paths.expressions.count \
  --depencity-accept depencity \
  --task "$(cat experiments/path-expressions-strict-target-10/task.md)" \
  --log-root "$PWD/out/experiments/path-expressions-strict-target-10"
```

Each turn requests 10 internal candidate attempts, retaining the best tested
state. The runner independently tests and measures the final candidate, rolling
back non-improving turns. Original fixtures stay untouched; accepted code carries
forward in the worker's two-file workspace. Logs remain outside the workspace.
