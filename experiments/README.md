# Benchmarks

`path-expressions-internal-20` runs one Depencity-enabled turn with 20 internal measured
candidate changes, per-candidate keep/revert decisions, and a strict final
complexity gate. See [its README](path-expressions-internal-20/README.md).

Each benchmark family lives in its own directory and compares the same prompt
with MCP enabled and without MCP. The `single-pass` family runs one paired pass
per case. The `multi-pass-no-target` family runs repeated sequential turns per
agent and preserves each intermediate diff and profile. It defaults to three
turns and accepts `--turns N`.
The `multi-pass-targeted` family adds a shared concise summary of the profile
targets from `target.json` to the task prompt.
