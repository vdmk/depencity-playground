# agent-runner

Run Codex iterations in any directory. Supply the task; workers use the runner's
explicit MCP configuration with their own workspace and the runner's build root.
The runner records output; evaluation is separate.

```sh
agent-runner run --iterations 20 --log-root /tmp/agent-runs
agent-runner run-workspaces --workers 50 --iterations 30 --log-root /tmp/agent-runs
```

Both commands require `--log-root` and accept `--repo`, `--task`, and `--model`.

`run` runs one worker in the supplied directory. Each iteration starts
from the previous iteration's edits. Git and commits are optional; the runner
leaves changes uncommitted. The default is one iteration.

`run-workspaces` runs independent candidates using Git worktrees. `--workers`
sets concurrency (default 5); `--iterations` sets iterations per worker (default 1).
For example, 50 workers with 30 iterations schedules up to 1,500 candidates.
`--branch-mode` selects the branch lifetime:

- `fresh` (default): each iteration creates a new branch and worktree from the
  coordinator branch's latest tip. Each changed iteration adds one commit.
- `incremental`: each worker keeps one branch and worktree for all iterations.
  Each iteration starts from that worker's previous commit. Different workers
  remain isolated from one another and from later coordinator changes.

Both branch modes require a clean Git repository. Commits use
`auto-refactor: <short_summary>`. Clean worktrees are removed when their context
ends (after each fresh iteration or after the whole incremental worker);
branches and commits remain available for review. Uncommitted changes preserve
the worktree. Nothing merges automatically.

Use `--depencity-eval` to copy the target and test script into an isolated
workspace and record metrics. Original files stay untouched. Repeat `--metric` to
record several. Passing changes carry forward even when metrics increase.

```sh
agent-runner run --depencity-eval --target calculator.py --iterations 3 \
  --test-script test_calculator.py --log-root /tmp/agent-runs
```

`run-experiment` runs the same prompt in parallel under `plain/` and `depencity/`;
only Depencity gets profiling tools. Both keep all changes that pass original tests in Docker.

```sh
agent-runner run-experiment --repo experiments/fixtures --target calculator.py \
  --test-script test_calculator.py --iterations 3 --log-root /tmp/comparisons
agent-runner run-experiment --iterations 6 --log-root /tmp/comparisons --continue
```

`--continue` reuses saved settings and progress. `--iterations` is the total per variant.

`--depencity-accept all|depencity` defaults to `all` (accept passing tests).
`depencity` also requires no selected metric increases and at least one decrease;
rejected candidates are logged and rolled back. Plain always accepts passing tests.
Also available for `run --depencity-eval`; saved across `--continue`.

The runner asks each worker to leave changes uncommitted and finish with a short
change summary in a structured `short_summary` field. Codex saves that reply to
a `.summary.json` file next to the logs. The runner supplies the `auto-refactor:`
commit prefix.
Sequential runs save the summary and leave edits uncommitted.
No-change iterations produce no commit. A nonzero Codex exit stops
that worker; other workers continue. The first Ctrl+C stops new iterations after
active iterations finish; the second interrupts the runner.

Set `--log-root` to a base log directory (absolute or relative to `--repo`).
Each run gets its own subdirectory; there is no default log directory.
Optional worktrees go under
`.worktrees/codex-batch/`. Ignore both directories when running in Git repositories.

`Codex` in `codex.py` executes an iteration. The `runners/` subpackage contains
`Runner` for scheduling, interruption, and shared Codex execution.
`FreshRunner` and `IncrementalRunner` own their `Git` instances and branch
lifetimes. `InPlaceRunner` runs directly in the supplied directory without
Git. The base runner knows nothing about branches or commits. `git.py` handles
Git operations.
Ordinary runners do not evaluate refactoring quality; `run --depencity-eval` opts into
the separate evaluator.

The package also provides `agent-runner-mcp` for Docker testing. See the [project README](../README.md) for its test setup.
