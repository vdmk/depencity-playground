# Expression-path internal search, 20 attempts

Run from the workspace root:

```sh
uv run agent-runner run --depencity-eval \
  --repo experiments/fixtures --target calculator.py --test-script test_calculator.py \
  --iterations 1 --metric graph.paths.expressions.count \
  --depencity-accept depencity \
  --task "$(cat experiments/path-expressions-internal-20/task.md)" \
  --log-root "$PWD/out/experiments/path-expressions-internal-20"
```

One Depencity-enabled agent turn attempts 20 candidate changes, keeping each
only when original Docker tests pass and whole-file expression-path count
strictly decreases from its latest accepted checkpoint. Failed candidates are
reverted inside the turn. Readability and behavior preservation remain required.
The model defaults to `gpt-6-luna`; override with `--model MODEL`.

This isolates internal search from the separate turns in `path-expressions`.
It starts from the original calculator fixture, not a previous run's result.
There is no plain arm because internal acceptance requires profiling access.
The runner independently validates the final candidate with original tests and
a strict complexity gate. Original fixtures remain untouched.

Artifacts go under `out/experiments/path-expressions-internal-20/`, including the transcript,
final evaluation, and worker-created `attempts.jsonl`. Inspect the attempt log
and transcript to verify completion: the 20-attempt requirement is a prompt
instruction, not a runner-enforced loop. The outer evaluator gates only the
final result; it does not independently enforce each internal decision.
