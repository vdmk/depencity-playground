# Agentic experiment playground

Extracted from `../complexity`. The `agent_runner/` subproject provides isolated
Codex workers, Docker execution, and review tools. `experiments/` contains the
calculator refactoring comparisons. Depencity comes from `../depencity` as an
editable dependency; its source stays in that repository.

Install with `uv sync`. Running experiments requires the `codex` CLI with a
configured account; MCP Docker tests also require Docker.

Repeat the calculator experiment with three sequential turns per variant:

```sh
uv run experiments/multi-pass-no-target/run.py --turns 3
uv run experiments/multi-pass-targeted/run.py --turns 3
```

Each compares agents with Depencity MCP tools against plain agents. Results,
profiles, diffs, tests, and transcripts go to `out/experiments/`. The targeted
variant can resume an interrupted run with `--resume`.

Other preserved comparisons:

```sh
uv run experiments/single-pass/run.py
uv run experiments/strict-targeted/run.py --help
```

Runner documentation: [agent_runner/README.md](agent_runner/README.md).
Profile preferences: [agent-runner-files/target.json](agent-runner-files/target.json).

Validate the runner through `agent-runner-mcp`'s `docker` tool, with build
root set to this directory, Dockerfile `docker/test/Dockerfile`, and command:
`pytest -q agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2`.
Test containers run with networking disabled.

The runner supplies `../depencity` as a named Docker build context and installs
it in the Alpine test image. For a manual build, run:

```sh
docker build --build-context depencity=/Users/xxx/workspace/depencity -f docker/test/Dockerfile .
```
