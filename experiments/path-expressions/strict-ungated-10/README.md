# Path expressions without metric gating

Run both Depencity and plain variants for 20 iterations each:

```sh
uv run agent-runner run experiments/path-expressions/strict-ungated-10/experiment.toml
```

Both variants start from the original calculator fixture and receive the same
prompt asking for 10 internal candidate attempts per invocation. Only Depencity
receives profiling tools. The harness accepts candidates that pass tests, including unchanged or increased
expression-path counts. The task is copied unchanged from `strict-target-10`;
it still instructs the agent to revert metric regressions internally.
The internal attempt budget is a prompt instruction, not enforced by the runner.

Metrics use the aggregate `__root__` profile. The earlier strict-target run used
module-scope metrics, so its numerical counts are not directly comparable.

Output goes to `out/experiments/path-expressions/strict-ungated-10/RUN_ID/`, with
separate `depencity/` and `plain/` directories. Resume with the same command
and `--continue`.

Generate a report:

```sh
python scripts/experiment_report.py out/experiments/path-expressions/strict-ungated-10/RUN_ID
```
