# Depencity agentic refactoring playground

This repository contains experiments in agentic refactoring using the Depencity library. It includes an agent runner and tools for reporting experiment results. Currently, only Codex CLI is supported.

The runner supports iterative experiments without Git commits, including evaluated runs used for reports, and an automated refactoring flow with dozens of agents working in separate Git worktrees.

## Getting started

Install dependencies with `uv sync`. Experiments require a configured `codex` CLI and Docker.

Run a plain-versus-Depencity comparison:

```sh
uv run agent-runner run experiments/path-expressions/simple/experiment.toml
```

Add `--continue` to resume the latest run with the same manifest. Settings and paths are defined in the manifest; see the [runner documentation](agent_runner/README.md) for modes and configuration.

## Experiments

The [experiment catalog](experiments/README.md) lists the checked-in tasks and manifests. Evaluated runs test candidates and record metrics, transcripts, diffs, and settings under `out/experiments/`. Historical runs are preserved under `out/archive/experiments/`.

## Reports and visualizations

Browse the [published reports](published/README.md). To regenerate a report, use the original run directory containing the per-turn evaluation records:

```sh
python scripts/experiment_report.py out/experiments/EXPERIMENT/RUN_ID
```

Generate code-change slideshows and videos:

```sh
uv run scripts/experiment_slideshow.py out/experiments/EXPERIMENT/RUN_ID
uv run scripts/experiment_video.py out/experiments/EXPERIMENT/RUN_ID/slideshow
```

Open the generated variant HTML files in `slideshow/`. Video rendering requires Google Chrome or a Chrome/Chromium executable supplied with `--chrome`.

## Validation

Use `agent-runner-mcp`'s `docker` tool with this directory as the build root and `docker/test/Dockerfile` to run:

```sh
pytest -q agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2
```

Test containers run with networking disabled. To build the image manually, run `docker build -f docker/test/Dockerfile .`.
