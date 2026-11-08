# agent-runner

Run Codex iterations in any directory. Supply the task and use the project's normal
Codex configuration. The runner records output; evaluation is separate.

```sh
agent-runner run-sequential --iterations 20 --log-root /tmp/agent-runs
agent-runner run-in-parallel --workers 50 --iterations 30 --log-root /tmp/agent-runs
```

Both commands require `--log-root` and accept `--repo`, `--task`, and `--model`.

`run-sequential` runs one worker in the supplied directory. Each iteration starts
from the previous iteration's edits. Git and commits are optional; the runner
leaves changes uncommitted. The default is one iteration.

`run-in-parallel` runs independent candidates using Git worktrees. `--workers`
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
lifetimes. `SequentialRunner` runs directly in the supplied directory without
Git. The base runner knows nothing about branches or commits. `git.py` handles
Git operations.
The runner does not call an evaluator or measure refactoring quality.

The package also provides `agent-runner-mcp` for Docker testing. See the [project README](../README.md) for its test setup.
