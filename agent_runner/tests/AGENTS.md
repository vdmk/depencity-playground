# Agent Runner Tests

Keep tests for Codex worktree orchestration, Docker test execution, and worktree
commits in this package. Use the shared pinned test image through MCP; do not run
pytest directly on the host.

Keep contract integration cases under `fixtures/runner/<case>/` or
`fixtures/mcp/<case>/`. Invoke the public Click commands and use FastMCP's
in-memory client for MCP requests. Keep request arguments in `input.*.json`
and compare MCP responses against `expected_output.mcp.json`. CLI tests can
assert exit codes and empty streams inline and use text snapshots for output.

Define subprocess calls and replies in the tests. Replies can include files
written by the mocked process. An unexpected or unused call fails the test.
Use `<tmp>` and `<project>` for machine-dependent paths. Update snapshots
deliberately when a public contract changes.

Run `tests/integration_old` explicitly to exercise the legacy suite.

Do not add absence assertions for removed implementation artifacts (for example,
checking that deleted snapshot filenames are not created). Test meaningful behavior.
