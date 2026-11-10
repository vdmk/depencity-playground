# Path expressions

Run the checked-in [manifest](experiment.toml):

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml
```

The manifest supplies the model, prompt file, iteration budget, metric, and
acceptance policy. Paths are relative to the manifest directory; `target` and
`test_script` are relative to `repo`.

Plain and Depencity variants run in parallel with the same prompt. Only Depencity receives profiling tools and requires metric improvement; plain retains changes that pass tests.
Original fixtures stay untouched. Each worker uses a persistent `workspace/`;
logs, candidate snapshots, diffs, evaluations, and resolved `run.toml` stay outside
it. Original tests are restored before Docker validation.

To resume the latest run, increase `[agent].iterations` in the manifest if
needed, then run:

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml --continue
```

Generate a self-contained HTML report:

```sh
python scripts/experiment_report.py out/experiments/path-expressions/RUN_ID
```

Historical runs from the CLI-argument interface are archived under
`out/archive/experiments/path-expressions/`. Their original logs and reports are preserved;
they cannot be resumed with the manifest interface.
