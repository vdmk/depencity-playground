# Agentic experiment playground

`agent_runner/` runs isolated Codex workers, Docker validation, and metric-guided
refactoring searches. `experiments/` defines reproducible calculator experiments
with TOML manifests.

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
Every execution saves effective settings in `metadata.json`, transcripts, diffs, test output,
and evaluations under `out/experiments/`. Resume the latest run with the same
manifest and `--continue`. Historical CLI-argument runs live under
`out/archive/experiments/` and remain unchanged.

Generate a self-contained HTML report:

```sh
python scripts/experiment_report.py out/experiments/EXPERIMENT/RUN_ID
```

Generate separate code-only slideshows, then render one video per variant:

```sh
uv run scripts/experiment_slideshow.py out/experiments/EXPERIMENT/RUN_ID
uv run scripts/experiment_video.py out/experiments/EXPERIMENT/RUN_ID/slideshow
```

Open `slideshow/depencity.html` or `slideshow/plain.html` directly. Use Play,
Previous/Next, arrow keys, or the iteration selector. Slides show saved before
and candidate code with eight context lines (adjust with `--context N`); rejected candidates appear before
rollback. Large changes span overlapping views, and long lines continue on the next
visual row. Changed words have stronger highlighting, and each view identifies
the enclosing function and iteration. No metrics are included.

Videos and their timeline JSON files are written under `slideshow/videos/`.
The renderer uses installed Google Chrome; pass `--chrome PATH` for another
Chrome/Chromium executable, `--seconds 3.5` for time per view, or `--output PATH`
for another destination. Playwright and FFmpeg are installed through the script's
isolated uv dependencies. Generated artifacts stay under `out/`.

See the [manifest and runner documentation](agent_runner/README.md) and
[experiment catalog](experiments/README.md).

Validate through `agent-runner-mcp`'s `docker` tool, using this directory as the
build root, `docker/test/Dockerfile`, and:

```sh
pytest -q agent_runner/tests -p no:cacheprovider --import-mode=importlib -n 2
```

Test containers run with networking
disabled. For a manual image build:

```sh
docker build -f docker/test/Dockerfile .
```
