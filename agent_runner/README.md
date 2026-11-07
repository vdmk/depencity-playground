# agent-runner

Run Codex turns in any directory. Supply the task and use the project's normal
Codex configuration. The runner records output; evaluation is separate.

```sh
agent-runner run --repo /path/to/project --iterations 3 --task 'Refactor calculator.py; do not commit.'
agent-runner run --repo /path/to/project --count 5 --iterations 10 --use-git --task 'Refactor and test one change.'
```

`run` defaults to one worker. Set `--count` for concurrent workers; more than one
worker requires `--use-git`. Git mode is off by default:

- Disabled: all turns use the supplied directory directly. Git and commits are
  optional, and uncommitted changes carry into the next turn. Only one worker
  is allowed in this mode.
- Enabled: a `Git` instance creates a fresh branch and worktree per worker
  iteration. It requires a clean Git repository. After a successful turn, the runner
  creates one commit per changed iteration on its own branch, using
  `auto-refactor: <short_summary>` as the commit message. Later iterations start from the coordinator branch's latest
  tip. Clean worktrees are removed on exit while their branches and commits remain
  available for review. Worktrees with uncommitted edits are preserved. Nothing
  merges automatically.

The runner asks each worker to leave changes uncommitted and finish with a short
change summary in a structured `short_summary` field. Codex saves that reply to
a `.summary.json` file next to the logs. The runner supplies the `auto-refactor:`
commit prefix.
With worktrees disabled, the summary is saved and edits remain uncommitted.
No-change turns produce no commit. A nonzero Codex exit stops
that worker; other workers continue. The first Ctrl+C stops new turns after
active turns finish; the second interrupts the runner.

Set `--log-root` to a base log directory (absolute or relative to `--repo`).
Each run gets its own subdirectory. The default is `agent-runner-files/logs/`.
Optional worktrees go under
`.worktrees/codex-batch/`. Ignore both directories when running in Git repositories.

`Codex` in `codex.py` executes a turn. `Runner` in `runner.py` owns run settings, the worker loop, and interruption.
`Runner.run()` schedules workers; `git.py` supplies the optional
`Git` class and its `NoGit` counterpart.
The runner does not call an evaluator or measure refactoring quality.

The package also provides `agent-runner-mcp` for Docker testing. See the [project README](../README.md) for its test setup.
