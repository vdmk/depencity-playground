# Agent runner

The agent runner uses Codex CLI to run refactoring experiments defined in TOML. It can edit a repository in place, evaluate candidates in an isolated workspace, or coordinate multiple agents in Git worktrees.

## Run an experiment

From the repository root, install dependencies with `uv sync`, configure Codex CLI, and make sure Docker is available. Then run a manifest:

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml
```

To resume the latest run for that manifest:

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml --continue
```

The manifest defines the experiment defaults. See the [experiment catalog](../experiments/README.md) for examples.

Use `--iterations` to override the total iterations per worker or variant. In workspaces mode, use `--workers` to override the number of workers.

```sh
uv run agent-runner run agent_runner/auto-refactor.toml --workers 3 --iterations 5
```

## Choose a mode

| Mode | How it works | Git and evaluation |
|---|---|---|
| `in-place` | Runs cumulative iterations directly in `repo`. | Leaves edits uncommitted; no Git management or evaluation. |
| `evaluated` | Each turn starts in a fresh temporary directory with the current target and original test script. The runner copies only the target back to the evaluation workspace for validation. Accepted edits carry forward to the next turn. | Original source files stay untouched; no commits are needed. |
| `workspaces` | Runs concurrent workers in separate Git worktrees. | The repository must be clean. The runner commits worker changes to branches; nothing merges automatically. |

In `workspaces` mode, set `workers` under `[agent]` and choose a top-level `branch_mode`. `fresh` creates a branch for each iteration from the coordinator branch's latest tip; `incremental` keeps one branch per worker and builds a commit chain. Workers are independent processes. Workspaces mode does not support resume.

## Configure a manifest

This example compares Codex with and without Depencity tools:

```toml
name = "calculator-expression-paths"
mode = "evaluated"
variants = ["depencity", "plain"]
repo = "../fixtures"
build_root = "../.."
dockerfile = "docker/test/Dockerfile"
log_root = "../../out/experiments/calculator-expression-paths"
task_file = "task.md"

[agent]
model = "gpt-6-luna"
iterations = 3

[evaluation]
target = "calculator.py"
test_script = "test_calculator.py"
metrics = ["graph.paths.expressions.count"]
reject_if_not_improved = "depencity"
```

`repo`, `log_root`, `task_file`, and `build_root` resolve relative to the manifest directory, regardless of the shell's working directory. `dockerfile` resolves inside the build root. Evaluation paths resolve relative to `repo` and must stay inside it. Use `task` for an inline prompt instead of `task_file`; specifying both is an error.

`build_root`, `dockerfile`, and `log_root` are required. Defaults are the manifest directory for `repo`, its directory name for `name`, `in-place` for `mode`, `gpt-6-luna` for `agent.model`, and one iteration. With neither task field, the runner uses a generic behavior-preserving refactoring task. Unknown fields, unsupported settings, invalid types, and out-of-range budgets are rejected before a run starts.

`agent.iterations` ranges from 1 to 1000 per worker or comparison variant. In workspaces mode, `agent.workers` ranges from 1 to 100 (default 5), and `branch_mode` defaults to `fresh`.

### Evaluated variants and acceptance

In evaluated mode, `variants` selects `["depencity"]` (the default), `["plain"]`, or both. Both variants use the same task and iteration budget and run in parallel; only the Depencity variant receives Depencity tools. Each selected variant has its own `depencity/` or `plain/` directory. Variants cannot change when resuming.

The `[evaluation]` section is required in evaluated mode and unsupported in other modes. `target` and `test_script` must name distinct existing files. `metrics` defaults to `["graph.paths.expressions.count"]` and must be a nonempty array of unique names. Measurements use the aggregate `__root__` profile, including descendant scopes.

Every candidate must pass the original tests. `reject_if_not_improved` controls the additional metric gate:

- `false` (default): neither variant requires metric improvement.
- `"depencity"`: only the Depencity variant requires improvement.
- `"all"`: every selected variant requires improvement.

When the gate applies, no selected metric may increase and at least one must decrease. Rejected candidates are logged and rolled back. Test failures continue the search; agent and infrastructure failures stop the affected worker.

## Records and resume

Each execution records effective settings, the complete prompt, repository commit, and Depencity version in `log_root/<timestamp>-<pid>/metadata.json`, alongside transcripts and other run artifacts. Repository, build-root, and log-root paths are relative to the record directory.

Use `--continue` with the same manifest to resume the latest run under its `log_root`, or pass a saved `metadata.json` to reuse its resolved settings. You may increase `agent.iterations` to extend the total, but cannot reduce it. Only iterations and `evaluation.reject_if_not_improved` may change; other effective settings, including prompt contents, must match.

Evaluated runs replay accepted and rejected checkpoints and retry interrupted or agent-failed iterations. In-place runs retain current files and skip iterations with a completed summary. To resume a run recorded before Docker settings were required, add `build_root` and `dockerfile` to its saved settings and manifest.

The first Ctrl+C stops new iterations after active ones finish; the second interrupts the runner. Each worker saves a structured `short_summary` beside its transcript.

### Worktree results

Workers leave edits uncommitted; the runner creates focused `auto-refactor: <short_summary>` commits. Clean worktrees are removed after a fresh iteration or after an incremental worker finishes. A worktree with uncommitted changes is preserved. Branches and commits remain for review and are never merged automatically.

## Reports and validation

Generate a self-contained HTML report for an evaluated run:

```sh
python scripts/experiment_report.py out/experiments/EXPERIMENT/RUN_ID
```

Workers can read and write their project folder and access minimal system runtime paths; logs are denied. Original tests are restored before validation. Docker runs tests with networking disabled and the workspace mounted read-only. The package provides `agent-runner-mcp` for Docker testing; see the [project README](../README.md) for setup and validation.

## Implementation and historical runs

`manifest.py` loads configuration and writes resolved TOML. `runner.py` selects the execution mode; `runners/` manages scheduling and workspace lifetimes; `evaluator.py` handles measurements, test gates, and rollback. Depencity remains an external analyzer dependency.

Historical argument-based runs remain under `out/archive/experiments/` with their original `run.json`, transcripts, and reports. The current interface cannot resume them or regenerate their reports.
