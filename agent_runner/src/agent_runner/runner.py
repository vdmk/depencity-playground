"""Run Codex turns, optionally in isolated Git worktrees."""
import os
import signal
import subprocess
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from .codex import Codex
from .git import Git, NoGit


DEFAULT_TASK = (
    'Make one coherent, behavior-preserving refactoring. Follow repository '
    'guidance and run relevant tests.'
)


@click.group()
def main() -> None:
    """Run independent candidates or cumulative refactoring turns."""


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
def run_sequential(repo, task, model, iterations, log_root) -> None:
    """Run cumulative turns in the supplied directory without Git commits."""
    _execute(repo, 1, task, model, iterations, False, log_root)


@main.command()
@click.option('--workers', type=click.IntRange(1, 100), default=5, show_default=True)
@click.option('--turns', type=click.IntRange(1, 1000), default=1, show_default=True,
              help='Turns per worker, each on an independent Git branch.')
@_common_options
def run_in_parallel(repo, workers, task, model, turns, log_root) -> None:
    """Run workers concurrently with a fresh Git branch for each turn."""
    _execute(repo, workers, task, model, turns, True, log_root)


def _execute(repo, count, task, model, iterations, use_git, log_root):
    try:
        repo = repo.resolve()
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}'

        log_root = (repo / log_root).resolve() / run_id
        log_root.mkdir(parents=True)

        codex = Codex(model, log_root)
        git = Git(repo, run_id) if use_git else NoGit(repo)

        successful = Runner(codex, repo, count, task, iterations, git).run()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise click.ClickException(str(error)) from error
    if not successful:
        raise click.exceptions.Exit(1)


class Runner:
    """Schedule Codex turns with optional worktree isolation."""

    def __init__(self, codex, repo, count, task, iterations, git):
        self.codex = codex
        self.repo = repo
        self.count = count
        self.task = (
            f'{task} Do not commit changes. '
            'Return a short_summary describing the change in one line. '
            'The agent caller will commit as "auto-refactor: {short_summary}".'
        )
        self.iterations = iterations
        self.git = git
        self.stopping = False

    def run(self) -> bool:
        previous_handler = signal.signal(signal.SIGINT, self.handle_interrupt)
        try:
            with ThreadPoolExecutor(max_workers=self.count) as workers:
                futures = {}
                for number in range(1, self.count + 1):
                    name = f'agent-{number:02d}'
                    futures[workers.submit(self.run_worker, name)] = name
                successful = True
                for future in as_completed(futures):
                    try:
                        successful &= future.result()
                    except (OSError, subprocess.CalledProcessError) as error:
                        click.echo(f'{futures[future]}: stopped after runner error ({error})')
                        successful = False
            click.echo('All current runs stopped; not relaunching agents.' if self.stopping
                       else 'No agents remain; stopping.')
            return successful
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    def handle_interrupt(self, _signum, _frame):
        if self.stopping:
            raise KeyboardInterrupt
        self.stopping = True
        click.echo('Stopping after current runs; press Ctrl+C again to interrupt the runner.')

    def run_worker(self, name):
        for iteration in range(1, self.iterations + 1):
            if self.stopping:
                break

            with self.git.create_workspace_branch(name, iteration) as branch:
                click.echo(f'{name}.{iteration}: launching')
                result = self.codex.run(f'{name}.{iteration}', branch.work_dir, self.task)
                click.echo(f'{name}.{iteration}: finished with return code {result.return_code}')
                if result.return_code != 0:
                    click.echo(f'{name}: stopped after nonzero exit')
                    return False
                branch.commit(result.short_summary)
        return True


if __name__ == '__main__':
    main()
