# Agent Runner Guidelines

These instructions cover runner development and its worker/reviewer workflows.
For analyzer implementation changes, follow `depencity/AGENTS.md` as well.

The agent-runner MCP does not expose a commit tool. Automated workers leave
changes uncommitted and return the requested summary; the runner creates their
commits when worktrees are enabled.

Use [approval guidance](../agent-runner-files/approval_guidance.md) when judging
refactorings and module placement. Paths in the workflow below are relative to
the workspace root. Worker execution, Docker validation, and commit review belong
to this package; do not introduce a runtime dependency on Depencity.

## Complexity-Driven Refactoring Loop

Treat the profile as a directional sensor, not as an ideal-score evaluator. The
LLM chooses the design; the analyzer supplies evidence about where complexity
is concentrated and whether a change actually balanced it.

For small finite conditionals, prefer explicit `if`/`elif` branches when they
make the transformation and its semantics clearer. Do not replace simple
control flow with a temporary lookup dictionary or tuple table merely to reduce
a profile counter; treat that as relocated complexity.

## Public and Private Scopes

Documented public APIs define the compatibility contract. Names inside
underscore-prefixed packages are implementation details unless explicitly
exported as public APIs. Private functions and methods are implementation details
underneath their public callers. Evaluate private complexity in the context of the public
behavior it supports; private signatures are not compatibility boundaries.
Private helpers may be merged or removed when that simplifies the
public call graph and preserves public behavior. Do not preserve a private
wrapper merely because it has its own scope.

For each refactoring iteration:

1. Capture a compact profile first. Request extended output only for a specific
   hotspot under investigation.
2. Diagnose the module as a whole: look for a simpler workflow, shared concept,
   or repeated operation spanning related functions. Choose one coherent,
   semantics-preserving simplification; do not settle for an isolated syntax
   edit or enlarge the diff for its own sake. Prefer removing duplicate
   operations, dead bookkeeping, repeated node construction, and unnecessary
   wrappers over introducing generic abstractions.
3. Keep data and graph compatibility: preserve dependency meaning, node/edge
   direction, metric names, and public behavior. Extend fixture coverage
   when the change closes a previously untested analyzer case; do not add unit tests.
4. Run both package test suites through the local MCP `docker` tool with
   two `pytest-xdist` workers:
   `env PYTHONPATH=/workspace/depencity/src:/workspace/agent_runner/src pytest -q depencity/tests agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2`.
   Do not run `pytest` directly on the host.
5. Re-profile the same file or package and compare nodes, edges, scope counts,
   every affected direct scope, dependency-path counts, and maximum and p95 path
   lengths. A smaller counter is not sufficient if depth, readability, or
   semantic coverage gets worse.
6. When a refactoring succeeds, search for analogous cases. Apply and measure
   each one separately; revert any that do not improve the code and profile.

Profile improvement is necessary, not sufficient. Reject marginal syntax-only
edits—such as inlining a useful one-use name or replacing a clear branch with a
conditional expression—unless the source is materially clearer or removes
meaningful work or dependencies. A tiny node, edge, or scope reduction alone is
not a reason to commit.

Use the local complexity MCP as the primary measurement and workspace boundary:
compact profile, read, write, and re-profile. MCP does not replace design
judgment; it makes the refactoring loop observable, repeatable, and safe.

## Supervised Production Improver Workflow

The improver may be used on production code as a supervised commit-producing
assistant. A commit is a reversible checkpoint, not an automatic approval.

For every accepted iteration:

1. Write only inside the MCP workspace boundary and inspect the current diff.
2. Run relevant tests and the complete suite through MCP `docker`; do not
   invoke host `pytest`.
3. Capture before/after compact profiles and include the meaningful metric deltas
   with the change summary.
4. Create one focused commit with a `refactor:` prefix.
5. Leave the commit available for human review; do not merge, push, or silently
   amend it. A reviewer may keep or revert that specific commit afterward.

Always use the MCP `docker` tool for validation, with the in-workspace
`docker/test/Dockerfile` and an explicit command such as
`env PYTHONPATH=/workspace/depencity/src:/workspace/agent_runner/src pytest -q depencity/tests agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2`.
The Dockerfile may install
dependencies with network access during `docker build`; the test container
must run with network disabled.

Do not commit failed or rejected experiments. Restore rejected edits completely
before starting the next iteration, and keep the worktree clean between
iterations. The agent is responsible for producing evidence and reversible
checkpoints; the human remains responsible for final acceptance.

Reject changes that merely relocate complexity into a new helper, lookup table,
temporary container, or deeper call chain. An added scope is acceptable only
when it removes materially more graph complexity or a real repeated concept.
Stop when remaining changes are speculative, trade away clarity, or require
changing the data model rather than simplifying its implementation.

Prefer the equivalent form with fewer external dependencies. Do not replace a
generator comprehension with `map` merely to remove an incidental comprehension
scope: `map` introduces an external dependency in the data graph, so that is not
a net simplification even when scope or node counters decrease.

## Multi-Agent Worktree Refactoring

Each worker uses its own worktree and branch. The user selects the commits to
integrate into `main`.

Record every reviewed worker commit in
`agent-runner-files/reviewed.jsonl`, including duplicates and rejected
candidates. Append one JSON object per line:

```json
{"commit":"<hash>","status":"accepted|rejected|superseded","message":"<commit message>","reason":"<short reason>"}
```

Keep the commit message in the `message` field. Use `superseded` for an
equivalent change already reviewed under another hash, so future sessions do
not review the same patch again.

After each run, present the worker commits and their validation results to the
user. Wait for their selection. Cherry-pick only the selected commits onto
`main`, in iteration order. Validate the integrated
changes with the runner suite through Docker MCP and compare the package profile
with the run record. Record review decisions in the ledger above.

Before deleting the local run branch, use `git cherry main <run-branch>` to
check for patches that are still unique to it. Keep the branch while any patch awaits a decision. Once integration is verified
and the user has finished selecting commits, record the disposition of the
remaining patches and delete the local run branch. Preserve the branch if a conflict or unexpected
validation failure leaves integration incomplete.

Workers leave edits in their worktrees and return a short summary. The runner
creates the worker commits. The coordinator performs the cherry-picks and cleanup.

Workers read the local ledger directly to search prior decisions and use
`docker` to run tests. The runner creates their Git checkpoints from the returned summary.
The coordinator uses only
`docker`; it does not create commits through the
agent-runner MCP. Append each decision directly to
`agent-runner-files/reviewed.jsonl` using the format above.

Named directional target profiles are recorded in
[target.json](../agent-runner-files/target.json).
Use them as evolving preferences for refactoring decisions; do not turn them
into a universal ideal score.

## Refactoring methods

- **Extract variable:** name a repeated or non-obvious expression and reuse it.
- **Inline variable:** replace a trivial, single-use variable with its value.
- **Split variable:** give distinct values or successive meanings distinct names.
- **Remove dead code:** delete unused definitions, parameters, branches, and
  assignments.
- **Remove duplication:** compute repeated work once and reuse the result.
- **Substitute algorithm:** replace an unnecessarily complex algorithm with a
  simpler equivalent.
- **Simplify expression:** reduce boolean, arithmetic, or conditional logic to
  an equivalent simpler expression.
- **Consolidate conditional:** combine conditions or branches with identical
  outcomes.
- **Decompose conditional:** name meaningful parts of a dense condition or
  branch.
- **Replace nested conditional with guard clauses:** return or continue early
  to remove unnecessary nesting.
- **Consolidate duplicate branches:** move identical work out of alternatives.
- **Remove control flag:** replace state used only to steer control flow with
  direct returns, breaks, or loop conditions.
- **Extract function:** name and isolate a cohesive operation or repeated
  behavior.
- **Inline function:** replace a trivial forwarding or one-use helper with its
  body.
- **Move statements:** place behavior with the caller or function that owns its
  data and purpose.
- **Remove parameter:** delete an argument that is unused or derivable without
  obscuring dependencies.
- **Add or change parameter:** pass a needed dependency explicitly instead of
  hiding it in unrelated state.
- **Parameterize function:** combine genuinely duplicated functions that differ
  only by a value or operation.
- **Replace parameter group with data value:** group values that form a real
  concept and are used together.
- **Replace temporary with query:** derive a value where needed instead of
  storing it, when this does not repeat costly or stateful work.
- **Replace query with parameter:** compute a value once and pass it when that
  avoids repeated work or hidden dependencies.
- **Separate query from modifier:** separate value-producing work from mutation.
- **Consolidate error handling:** combine handlers that apply the same policy;
  remove handlers that only re-raise unchanged errors.
- **Replace exception with precheck, or precheck with exception handling:** use
  the clearer correct form without duplicate work or race conditions.
- **Replace loop with comprehension or generator:** express simple collection
  transformations directly.
- **Replace comprehension with loop:** make multi-step work, mutation, or early
  exit explicit.
- **Combine loops:** traverse the same data once when doing so keeps operations
  clear and ordered.
- **Split loop:** separate distinct phases when one loop obscures their purpose.
- **Remove temporary collection:** stream or iterate directly when the values
  are not reused or mutated.
- **Introduce temporary collection:** materialize values when reuse, mutation,
  or evaluation timing requires it.
- **Replace manual iteration with a built-in:** use direct iteration,
  `enumerate`, `zip`, unpacking, or a standard operation to remove bookkeeping.
- **Inline class or module:** remove a container that only forwards or groups
  behavior without adding a useful concept.
- **Extract class or module:** group behavior only when it establishes a real,
  cohesive responsibility and simplifies its callers.
- **Move definition:** place a function or value beside the data and behavior it
  belongs to.
- **Replace derived state with a query:** stop storing a value that can be
  reliably derived from existing state.
- **Replace repeated literal with a named constant:** name a value when the name
  explains its meaning or prevents inconsistent repetition.

Use these as candidate transformations, not prescriptions. Ignore inheritance
and design-pattern refactorings unless the specific code makes them relevant.
