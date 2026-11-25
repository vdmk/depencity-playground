# Agent Runner Guidelines

These instructions cover runner development and worker/reviewer workflows. Paths
below are relative to the workspace root.

## Complexity-driven refactoring

Use the local complexity MCP as the primary workspace and measurement boundary
for profiling, reading, and writing. Treat profiles as directional evidence;
the agent remains responsible for design judgment.

For each iteration:

1. Capture a compact profile; request extended output only for a specific hotspot.
2. Diagnose the module as a whole and choose one coherent, behavior-preserving
   simplification. Look for simpler workflows, shared concepts, duplicate work,
   dead bookkeeping, repeated node construction, and unnecessary wrappers.
3. Preserve public behavior, dependency meaning, node/edge direction, and metric
   names. Documented public APIs are the compatibility boundary; underscore
   packages and private helpers are implementation details unless explicitly
   exported. Merge or remove private helpers when that simplifies the public call
   graph. Extend fixture coverage for previously untested analyzer cases; do not
   add unit tests.
4. Inspect the diff and run relevant tests and the runner suite using the MCP
   `docker` tool, `docker/test/Dockerfile`, and two pytest-xdist workers:

   ```sh
   pytest -q agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2
   ```

   Do not run pytest on the host. The Docker build may use network access to
   install dependencies; the test container must run with networking disabled.
5. Re-profile the same file or package. Compare nodes, edges, scope counts, all
   affected direct scopes, dependency-path counts, and maximum and p95 path
   lengths. Include meaningful before/after deltas in the change summary.
6. If successful, look for analogous cases; apply and measure each separately.
   Restore rejected edits completely before the next iteration.

Profile improvement is necessary but not sufficient. Reject changes that merely
move complexity into helpers, lookup tables, temporary containers, or deeper
call chains, or that reduce a counter at the expense of clarity, depth, or semantic
coverage. An added scope should remove materially more graph complexity or a real
repeated concept. Avoid marginal syntax-only changes and diffs enlarged for their
own sake. Prefer clear `if`/`elif` branches for small finite conditionals when
appropriate, and prefer equivalent forms with fewer external dependencies; do
not replace a generator comprehension with `map` merely to remove a scope. Stop
when remaining changes are speculative, reduce clarity, or require changing the
data model rather than simplifying its implementation.

## Supervised production improver

For each accepted iteration, keep the worktree clean between iterations and create
one focused `refactor:` commit after the validation and profiling above. Do not
commit failed or rejected experiments. Leave each commit for human review; do not
merge, push, or silently amend it. A commit is a reversible checkpoint, and the
human decides whether to keep it.

## Multi-agent worktrees

Each worker has its own worktree and branch. The agent-runner MCP has no commit
tool: workers leave edits uncommitted and return a short summary; the runner
creates their commits. Workers and the coordinator use MCP `docker` for testing
and validation.

After a run, present worker commits and validation results to the user and wait
for their selection. Cherry-pick only selected commits onto `main` in iteration
order. Validate the integrated changes with the runner suite through Docker MCP
and compare the package profile with the run record.

Before deleting a local run branch, run `git cherry main <run-branch>` to find
patches still unique to it. Keep the branch while any patch awaits a decision or
integration is incomplete because of a conflict or unexpected validation failure.
Once integration is verified and the user has finished selecting commits, record
the disposition of remaining patches and delete the local run branch. The
coordinator handles cherry-picks and cleanup.

## Refactoring candidates

Order functions and methods from higher to lower levels of abstraction. Put
public entry points and orchestration first, then the helpers they call, with
low-level implementation details last.

Choose transformations that simplify the actual code, not as prescriptions:

- Name, inline, split, or remove variables; remove dead code and duplicate work.
- Simplify expressions and conditionals, use guard clauses, and remove control
  flags where direct control flow is clearer.
- Extract, inline, move, or parameterize functions and definitions; group
  parameters or extract classes and modules only for cohesive concepts.
- Replace unnecessary temporary or derived state with queries, or pass computed
  values explicitly when that avoids repeated work or hidden dependencies.
- Separate queries from modifiers and consolidate or simplify error handling.
- Combine or split loops, use comprehensions or generators where clear, and
  materialize collections when reuse, mutation, or evaluation timing requires it.
- Use suitable built-ins and named constants to remove bookkeeping or clarify meaning.
- Substitute a simpler algorithm when it preserves behavior.

Ignore inheritance and design-pattern refactorings unless the code makes them relevant.
