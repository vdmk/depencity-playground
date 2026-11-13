# Experiment catalog

Each experiment has a checked-in `experiment.toml` and a Markdown task. Run it
with `uv run agent-runner run experiments/NAME/experiment.toml`.

| Experiment | Variants | Iterations | Search prompt |
|---|---|---:|---|
| [path-expressions/simple](path-expressions/simple/experiment.toml) | depencity, plain | 3 per variant | Shared plain-versus-Depencity task |
| [path-expressions/internal-20](path-expressions/internal-20/experiment.toml) | depencity | 10 | Continued search without a fixed internal attempt count |
| [path-expressions/strict-target-10](path-expressions/strict-target-10/experiment.toml) | depencity, plain | 20 | Requests ten internal candidates per turn |

| [path-expressions/strict-ungated-10](path-expressions/strict-ungated-10/experiment.toml) | depencity, plain | 20 | Ten internal attempts; passing candidates may increase metrics |

All use the original [calculator fixture](fixtures/calculator.py), Docker tests,
and `graph.paths.expressions.count`. All candidates must pass tests. Depencity additionally requires metric improvement
except in `strict-ungated-10`, where both variants accept passing candidates regardless
of metric changes. These manifests apply no metric gate to plain.
The internal attempt count remains a prompt instruction, not a harness-enforced
budget.

Each manifest specifies its output directory under `out/experiments/`, including
a resolved `run.toml`. Existing experiment names and output paths are preserved.
Use `--continue` with the same manifest to resume; edit `agent.iterations` to
increase the total. See the [runner documentation](../agent_runner/README.md)
for the complete schema and resume rules.

Historical argument-based runs and their original reports are preserved under
`out/archive/experiments/`. New reports read resolved TOML records:

```sh
python scripts/experiment_report.py out/experiments/NAME/RUN_ID
```

## Decomposition

[decomposition/strict-ungated-10](decomposition/strict-ungated-10/experiment.toml)
compares Depencity and plain over 40 iterations each. It targets the maximum
per-function distinct variable dependency count, with whole-file expression paths
as a tie-breaker. See its [README](decomposition/strict-ungated-10/README.md) for
measurement and harness limitations.

[decomposition-calls/strict-ungated-10](decomposition-calls/strict-ungated-10/experiment.toml)
adds whole-file static call count to the decomposition objectives, retaining
20 iterations per variant and the ungated harness. See its
[README](decomposition-calls/strict-ungated-10/README.md) for acceptance rules.
