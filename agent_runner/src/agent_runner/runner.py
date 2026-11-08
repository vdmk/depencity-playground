"""Run Codex iterations, optionally in isolated Git worktrees."""
import os
from datetime import datetime, timezone
from pathlib import Path

import click

from agent_runner.cli_utils import cli_errors
from agent_runner.codex import Codex
from agent_runner.runners.fresh import FreshRunner
from agent_runner.runners.incremental import IncrementalRunner
from agent_runner.runners.in_place import InPlaceRunner


DEFAULT_TASK = (
    'Make one coherent, behavior-preserving refactoring. Follow repository '
    'guidance and run relevant tests.'
)


@click.group()
def main() -> None:
    """Run independent candidates or cumulative refactoring iterations."""


def _common_options(command):
    for option in reversed([
        click.option('--log-root', type=click.Path(path_type=Path),
                     required=True, help='Base log directory, relative to --repo or absolute.'),
        click.option('--repo', type=click.Path(path_type=Path), default=Path.cwd),
        click.option('--task', default=DEFAULT_TASK, help='Task for each fresh agent session.'),
        click.option('--model', default='gpt-6-luna', show_default=True),
    ]):
        command = option(command)
    return command

@main.command()
@click.option('--iterations', type=click.IntRange(1, 1000), default=1, show_default=True)
@_common_options
@cli_errors
def run(repo, task, model, iterations, log_root) -> None:
    """Run cumulative iterations in the supplied directory without Git commits."""
    repo, log_root, _ = _build_context(repo, log_root)

    successful = InPlaceRunner(Codex(model, log_root), repo, task, iterations).run()
    if not successful:
        raise click.exceptions.Exit(1)


@main.command()
@click.option('--workers', type=click.IntRange(1, 100), default=5, show_default=True)
@click.option('--branch-mode', type=click.Choice(['fresh', 'incremental']),
              default='fresh', show_default=True, help='Fresh branch per iteration or one incremental branch per worker.')
@click.option('--iterations', type=click.IntRange(1, 1000), default=1, show_default=True,
              help='Number of iterations per worker.')
@_common_options
@cli_errors
def run_workspaces(repo, workers, task, model, iterations, log_root, branch_mode) -> None:
    """Run workers concurrently using the selected branch strategy."""
    repo, log_root, run_id = _build_context(repo, log_root)
    runner_class = FreshRunner if branch_mode == 'fresh' else IncrementalRunner

    successful = runner_class(Codex(model, log_root), repo, workers, task, iterations, run_id).run()
    if not successful:
        raise click.exceptions.Exit(1)


def _build_context(repo: Path, log_root: Path) -> tuple[Path, Path, str]:
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}'

    repo = repo.resolve()
    log_root = (repo / log_root).resolve() / run_id
    log_root.mkdir(parents=True)
    return repo, log_root, run_id

if __name__ == '__main__':
    main()
