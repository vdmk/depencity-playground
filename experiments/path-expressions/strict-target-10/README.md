# Path expressions strict target 10

Run the checked-in [manifest](experiment.toml):

```sh
uv run agent-runner run experiments/path-expressions/strict-target-10/experiment.toml
```

The manifest supplies the model, prompt file, iteration budget, metric, and
acceptance policy. Paths are relative to the manifest directory; `target` and
`test_script` are relative to `repo`.

Depencity and plain workers each run 20 cumulative iterations in parallel.
Depencity retains a candidate only when tests pass and the expression-path count
decreases; plain retains every candidate that passes tests.
Original fixtures stay untouched. Each worker uses a persistent `workspace/`;
logs, candidate snapshots, diffs, evaluations, and run metadata stay outside
it. Original tests are restored before Docker validation.

To resume the latest run, increase `[agent].iterations` in the manifest if
needed, then run:

```sh
uv run agent-runner run experiments/path-expressions/strict-target-10/experiment.toml --continue
```

Generate a self-contained HTML report:

```sh
python scripts/experiment_report.py out/experiments/path-expressions-strict-target-10/RUN_ID
```

Historical runs from the CLI-argument interface are archived under
`out/archive/experiments/path-expressions-strict-target-10/`. Their original logs and reports are preserved;
they cannot be resumed with the manifest interface.
