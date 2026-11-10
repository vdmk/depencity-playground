# agent-runner

Run Codex refactoring searches from a TOML experiment definition:

```sh
agent-runner run experiments/path-expressions/experiment.toml
agent-runner run experiments/path-expressions/experiment.toml --continue
```

The CLI accepts a manifest and an optional `--continue`. All experiment settings
live in TOML; the former configuration flags and separate run commands are removed.

## Manifest

```toml
name = "calculator-expression-paths"
mode = "comparison"
repo = "../fixtures"
log_root = "../../out/experiments/calculator-expression-paths"
task_file = "task.md"

[agent]
model = "gpt-6-luna"

iterations = 3

[evaluation]
target = "calculator.py"
test_script = "test_calculator.py"
metrics = ["graph.paths.expressions.count"]
acceptance = "depencity"
```

`repo`, `log_root`, and `task_file` resolve relative to the manifest's directory,
regardless of the shell's working directory. Evaluation paths resolve relative
to `repo` and must stay inside it. Use `task = "..."` for an inline prompt instead
of `task_file`; specifying both is an error.

`log_root` is required. Defaults are the manifest directory for `repo`, its
directory name for `name`, `in-place` for `mode`, `gpt-6-luna` for `agent.model`,
and one iteration. Omitting both task fields uses a generic behavior-preserving
refactoring task. Unknown fields, unsupported mode settings, invalid types,
and out-of-range budgets are rejected before creating a run.

## Modes

- `in-place`: cumulative iterations directly in `repo`, without Git management.
  Edits remain uncommitted; no evaluator runs.
- `evaluated`: copy the target and original test script into an isolated
  `workspace/`. Measure and Docker-test each candidate, retaining accepted edits.
  Original source files stay untouched.
- `comparison`: run evaluated `plain/` and `depencity/` variants in parallel with
  the same prompt. Only Depencity receives profiling tools.
- `workspaces`: concurrent workers in isolated Git worktrees. Add
  `workers = 5` under `[agent]` and top-level `branch_mode = "fresh"`. Both require this
  mode. The repository must be clean. `fresh` creates one branch per iteration
  from the coordinator branch's latest tip; `incremental` keeps one branch per
  worker and builds a commit chain. Nothing merges automatically.

`agent.iterations` is 1–1000, per worker or comparison variant.
`agent.workers` is 1–100, default 5. `branch_mode` defaults to `fresh`.
Workers are independent processes managed by the runner.

`[evaluation]` is required for evaluated and comparison modes and unsupported
in the other modes. `target` and `test_script` must name distinct existing files.
`metrics` defaults to `["graph.paths.expressions.count"]` and must be a nonempty
array of unique metric names.

`acceptance = "all"` (default) retains candidates that pass original tests.
`acceptance = "depencity"` also requires no selected metric increases and at least
one decrease. In comparison mode this metric gate applies only to Depencity;
plain always retains candidates that pass tests. Rejected candidates are logged
and rolled back. Test failures continue the search; agent and infrastructure
failures stop the affected worker.

## Run records and resume

Each execution creates `log_root/<timestamp>-<pid>/run.toml`. This resolved
manifest saves every effective setting, absolute repository and log-root paths,
and the complete prompt text. It does not depend on the original prompt file.
Logs, summaries, candidate snapshots, diffs, and evaluations sit beside it.
These are execution records, not a sanitized publication bundle.

Use the same experiment manifest with `--continue` to resume the latest run under
its `log_root`. Increase `agent.iterations` to extend the total; it cannot be
reduced. Only iterations and evaluation acceptance may change when continuing.
Other effective settings, including prompt contents, must match. Alternatively,
pass a saved `run.toml` itself to reuse its resolved settings.

Evaluated runs replay accepted/rejected checkpoints and retry interrupted or
agent-failed iterations. In-place runs retain current files and skip iterations
with a completed summary. Workspaces mode does not support resume.

Worktree workers leave changes uncommitted; the runner creates focused
`auto-refactor: <short_summary>` commits. Clean worktrees are removed after a fresh
iteration or after an incremental worker finishes. Uncommitted changes preserve
the worktree. Branches and commits remain for review.

The first Ctrl+C stops new iterations after active ones finish; the second
interrupts the runner. Each worker finishes with a structured `short_summary`
record saved beside its transcript.

## Reports and runtime

Generate a self-contained HTML report for an evaluated or comparison run:

```sh
python scripts/experiment_report.py out/experiments/EXPERIMENT/RUN_ID
```

Workers can read/write their project folder and access minimal system runtime
paths; logs are denied. Original tests are restored before validation. Docker
runs tests with networking disabled and the workspace mounted read-only.
The package provides `agent-runner-mcp` for Docker testing; see the
[project README](../README.md) for setup and validation.

`manifest.py` owns configuration loading and resolved TOML writing. `runner.py`
selects the execution mode. `runners/` owns scheduling and workspace lifetimes;
`evaluator.py` owns measurements, test gates, and rollback. Depencity remains an
external analyzer dependency.

Historical argument-based runs are preserved under `out/archive/experiments/`.
They retain their original `run.json`, transcripts, and generated reports; the
new interface does not resume them or regenerate their reports.
