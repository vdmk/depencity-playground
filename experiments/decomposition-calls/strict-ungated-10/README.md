# Decomposition and calls without metric gating

Based on `decomposition/strict-ungated-10`, with the same task except for adding
`call.occurrences.total.count` as an objective alongside the maximum per-function
`variable.total.read.distinct_count`. Both variants start from the original
calculator fixture, with the same model, 20 iterations per variant, and ten
internal candidate attempts.

```sh
uv run agent-runner run experiments/decomposition-calls/strict-ungated-10/experiment.toml
```

Neither primary metric may increase. At least one must decrease, or both must
stay equal while whole-file `graph.paths.expressions.count` decreases. Tests
must pass. Static call occurrences count source call sites, not runtime calls.

As in the source experiment, the agent computes the per-function maximum from
function `own_profile` values, including nested functions and methods. The
harness records root aggregates, including the added call count, and accepts
any passing candidate; the objective is applied internally by the agent, not
enforced by the harness. Root distinct reads are not the per-function maximum.
Both variants receive the same task; only Depencity receives profiling tools.
The ten internal attempts remain a prompt instruction.

Outputs go to `out/experiments/decomposition-calls/strict-ungated-10/RUN_ID/`.
