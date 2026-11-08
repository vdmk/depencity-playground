# Agent Runner Tests

Keep tests for Codex worktree orchestration, Docker test execution, and worktree
commits in this package. Use the shared pinned test image through MCP; do not run
pytest directly on the host.

Do not add absence assertions for removed implementation artifacts (for example,
checking that deleted snapshot filenames are not created). Test meaningful behavior.
