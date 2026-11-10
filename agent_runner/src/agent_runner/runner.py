"""Run manifest-defined refactoring searches."""

import os
from datetime import datetime, timezone
from pathlib import Path

import click

from agent_runner.cli_utils import cli_errors
from agent_runner.codex import Codex
from agent_runner.manifest import DEFAULT_TASK, load_manifest, save_manifest
from agent_runner.runners.comparison import ComparisonRunner
from agent_runner.runners.evaluated import EvaluatedRunner
from agent_runner.runners.fresh import FreshRunner
from agent_runner.runners.incremental import IncrementalRunner
from agent_runner.runners.in_place import InPlaceRunner


@click.group()
def main() -> None:
    """Run refactoring experiments defined by TOML manifests."""


@main.command()
@click.argument('manifest', type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--continue', 'resume', is_flag=True,
              help='Resume the latest run in the manifest log_root; iterations is the total.')
@cli_errors
def run(manifest: Path, resume: bool) -> None:
    """Run MANIFEST, saving its resolved settings alongside the results."""
    settings = load_manifest(manifest)
    mode = settings['mode']
    base = Path(settings['log_root'])
    if resume:
        if mode == 'workspaces':
            raise click.UsageError('workspaces mode does not support --continue')
        manifests = sorted(base.glob('*/run.toml'))
        if not manifests:
            raise click.ClickException(f'no run to continue under {base}')
        log_root = manifests[-1].parent
        saved = load_manifest(manifests[-1])
        if settings['iterations'] < saved['iterations']:
            raise click.UsageError('agent.iterations cannot be less than the saved total')
        if any(value != saved.get(key) for key, value in settings.items()
               if key not in ('iterations', 'depencity_accept')):
            raise click.ClickException('manifest settings differ from the saved run')
    else:
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}'
        log_root = base / run_id
        log_root.mkdir(parents=True)
    save_manifest(log_root / 'run.toml', settings)
    click.echo(f'Run: {log_root}')
    repo = Path(settings['repo'])
    task, model, iterations = (settings[key] for key in ('task', 'model', 'iterations'))
    if mode == 'evaluated' and len(settings['variants']) > 1:
        runner = ComparisonRunner(
            repo, log_root, task, model, iterations, Path(settings['target']),
            tuple(settings['metrics']), Path(settings['test_script']), resume,
            settings['depencity_accept'], variants=settings['variants'],
        )
    else:
        directory = log_root / settings['variants'][0] if mode == 'evaluated' else log_root
        directory.mkdir(parents=True, exist_ok=True)
        codex = Codex(model, directory, with_depencity=settings.get('variants', ['depencity']) != ['plain'])
        if mode == 'evaluated':
            runner = EvaluatedRunner(
                codex, repo, task, iterations, Path(settings['target']), tuple(settings['metrics']),
                Path(settings['test_script']), workspace=directory / 'workspace', resume=resume,
                depencity_accept=settings['depencity_accept'] if settings['variants'] == ['depencity'] else 'all',
            )
        elif mode == 'workspaces':
            runner_class = FreshRunner if settings['branch_mode'] == 'fresh' else IncrementalRunner
            runner = runner_class(codex, repo, settings['workers'], task, iterations, log_root.name)
        else:
            runner = InPlaceRunner(codex, repo, task, iterations, resume=resume)
    if not runner.run():
        raise click.exceptions.Exit(1)


if __name__ == '__main__':
    main()
