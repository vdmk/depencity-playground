# agent-runner

Run Codex turns in any directory. Supply the task and use the project's normal
Codex configuration. The runner records output; evaluation is separate.

```sh
agent-runner run-sequential --iterations 20 --log-root /tmp/agent-runs
agent-runner run-in-parallel --workers 50 --turns 30 --log-root /tmp/agent-runs
```

Both commands require `--log-root` and accept `--repo`, `--task`, and `--model`.

`run-sequential` runs one worker in the supplied directory. Each iteration starts
from the previous iteration's edits. Git and commits are optional; the runner
leaves changes uncommitted. The default is one iteration.

`run-in-parallel` runs independent candidates using Git worktrees. `--workers`
sets concurrency (default 5); `--turns` sets turns per worker (default 1).
For example, 50 workers with 30 turns schedules up to 1,500 candidates. Each turn
creates a fresh branch and worktree from the coordinator branch's latest tip.
The command requires a clean Git repository and creates one commit per changed
turn using `auto-refactor: <short_summary>` as the message. Clean worktrees are
removed on exit; branches and commits remain available for review. Uncommitted
changes preserve the worktree. Nothing merges automatically.

The runner asks each worker to leave changes uncommitted and finish with a short
change summary in a structured `short_summary` field. Codex saves that reply to
a `.summary.json` file next to the logs. The runner supplies the `auto-refactor:`
commit prefix.
Sequential runs save the summary and leave edits uncommitted.
No-change turns produce no commit. A nonzero Codex exit stops
that worker; other workers continue. The first Ctrl+C stops new turns after
active turns finish; the second interrupts the runner.

Set `--log-root` to a base log directory (absolute or relative to `--repo`).
Each run gets its own subdirectory; there is no default log directory.
Optional worktrees go under
`.worktrees/codex-batch/`. Ignore both directories when running in Git repositories.

`Codex` in `codex.py` executes a turn. `Runner` in `runner.py` owns run settings, the worker loop, and interruption.
`Runner.run()` schedules workers; `git.py` supplies the optional
`Git` class and its `NoGit` counterpart.
The runner does not call an evaluator or measure refactoring quality.

The package also provides `agent-runner-mcp` for Docker testing. See the [project README](../README.md) for its test setup.
