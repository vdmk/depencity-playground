# Agentic experiment playground

`agent_runner/` runs isolated Codex workers, Docker validation, and metric-guided
refactoring searches. `experiments/` defines reproducible calculator experiments
with TOML manifests. Depencity comes from `../depencity` as an editable dependency.

Install with `uv sync`. Running experiments requires a configured `codex` CLI
and Docker. Start a plain-versus-Depencity comparison:

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml
```

Or run a Depencity-only search:

```sh
uv run agent-runner run experiments/path-expressions/strict-target-10/experiment.toml
```

Settings live in the manifest. Relative paths resolve from its directory.
Every execution saves a resolved `run.toml`, transcripts, diffs, test output,
and evaluations under `out/experiments/`. Resume the latest run with the same
manifest and `--continue`. Historical CLI-argument runs live under
`out/archive/experiments/` and remain unchanged.

Generate a self-contained HTML report:

```sh
python scripts/experiment_report.py out/experiments/EXPERIMENT/RUN_ID
```

See the [manifest and runner documentation](agent_runner/README.md) and
[experiment catalog](experiments/README.md).

Validate through `agent-runner-mcp`'s `docker` tool, using this directory as the
build root, `docker/test/Dockerfile`, and:

```sh
pytest -q agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2
```

Test containers run with networking disabled. The runner supplies `../depencity`
as a named Docker build context. For a manual image build:

```sh
docker build --build-context depencity=../depencity -f docker/test/Dockerfile .
```
