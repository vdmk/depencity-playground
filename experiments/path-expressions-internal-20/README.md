# Expression-path internal search

The current task asks for continued useful improvements without a fixed internal
attempt count or bookkeeping. Run 10 outer iterations with Depencity only:

```sh
uv run agent-runner run --depencity-eval \
  --repo experiments/fixtures --target calculator.py --test-script test_calculator.py \
  --iterations 10 --metric graph.paths.expressions.count \
  --depencity-accept depencity \
  --task "$(cat experiments/path-expressions-internal-20/task.md)" \
  --log-root "$PWD/out/experiments/path-expressions-internal-20"
```

Each run starts from the original fixtures. One persistent `workspace/` contains
calculator.py and the original tests; logs and evaluation artifacts stay outside
it. Tests are restored each turn. The evaluator keeps candidates only when tests
pass and expression-path count decreases; rejected edits are rolled back.
Historical paired runs and their original 20-attempt prompts remain in the logs.
