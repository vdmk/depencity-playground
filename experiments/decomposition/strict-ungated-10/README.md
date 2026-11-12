# Decomposition without metric gating

Based on the latest `path-expressions/strict-ungated-10` run, with 20 iterations
per variant, the same fixture, model, and ten internal candidate attempts.

```sh
uv run agent-runner run experiments/decomposition/strict-ungated-10/experiment.toml
```

The primary objective is the maximum `variable.total.read.distinct_count` across
function `own_profile` values, including nested functions and methods. The
secondary objective is the `__root__` aggregate `graph.paths.expressions.count`.
Candidates improve lexicographically: lower the primary objective, or keep it
equal and lower the secondary objective. Tests must pass.

The maximum is computed by the agent from scope profiles, not enforced or saved
as a derived score by the harness. Saved evaluation metrics are root aggregates;
the root distinct-read count is not the per-function maximum. Inspect transcripts
for the agent's per-function measurements. Writes and call targets are recorded
as tradeoffs, not additional optimization gates. Both variants receive the same
task; only Depencity receives profiling tools. Internal attempts remain a prompt
instruction. The harness accepts any passing candidate, as in the source run.

Outputs go to `out/experiments/decomposition/strict-ungated-10/RUN_ID/`.
