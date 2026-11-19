"""Run manifest-defined refactoring searches."""

import os
import json
import subprocess
from importlib.metadata import PackageNotFoundError, version
from datetime import datetime, timezone
from pathlib import Path

import click

from agent_runner.cli_utils import cli_errors
from agent_runner.codex import Codex
from agent_runner.manifest import DEFAULT_TASK, load_manifest, latest_record, recorded_settings
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
        record = latest_record(base)
        if record is None:
            raise click.ClickException(f'no run to continue under {base}')
        log_root = record.parent
        saved = load_manifest(record)
        if settings['iterations'] < saved['iterations']:
            raise click.UsageError('agent.iterations cannot be less than the saved total')
        fixed_keys = (settings.keys() | saved.keys()) - {'iterations', 'reject_if_not_improved'}
        if any(settings.get(key) != saved.get(key) for key in fixed_keys):
            raise click.ClickException('manifest settings differ from the saved run')
    else:
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}'
        log_root = base / run_id
        log_root.mkdir(parents=True)
    if not resume:
        commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=settings['repo'],
            capture_output=True, text=True,
        )
        try:
            depencity_version = version('depencity')
        except PackageNotFoundError:
            depencity_version = None
        metadata = {
            'commit_hash': commit.stdout.strip() if commit.returncode == 0 else None,
            'depencity_version': depencity_version,
        }
    else:
        previous = log_root / 'metadata.json'
        metadata = json.loads(previous.read_text()) if previous.exists() else {}
    metadata['settings'] = recorded_settings(settings, log_root)
    pending = log_root / 'metadata.json.tmp'
    pending.write_text(json.dumps(metadata, indent=2) + '\n')
    pending.replace(log_root / 'metadata.json')
    click.echo(f'Run: {log_root}')
    if not _run_configured(settings, log_root, resume, mode):
        raise click.exceptions.Exit(1)


def _run_configured(settings, log_root, resume, mode) -> bool:
    """Build and execute the runner selected by the resolved settings."""
    repo = Path(settings['repo'])
    docker_options = dict(build_root=Path(settings['build_root']), dockerfile=settings['dockerfile'])
    task, model, iterations = (settings[key] for key in ('task', 'model', 'iterations'))
    if mode == 'evaluated' and len(settings['variants']) > 1:
        runner = ComparisonRunner(
            repo, log_root, task, model, iterations, Path(settings['target']),
            tuple(settings['metrics']), Path(settings['test_script']), resume,
            settings['reject_if_not_improved'], variants=settings['variants'], **docker_options,
        )
    else:
        directory = log_root / settings['variants'][0] if mode == 'evaluated' else log_root
        directory.mkdir(parents=True, exist_ok=True)
        codex = Codex(model, directory, with_depencity=settings.get('variants', ['depencity']) != ['plain'], **docker_options)
        if mode == 'evaluated':
            runner = EvaluatedRunner(
                codex, repo, task, iterations, Path(settings['target']), tuple(settings['metrics']),
                Path(settings['test_script']), workspace=directory / 'workspace', resume=resume,
                reject_if_not_improved=settings['reject_if_not_improved'] in ('all', settings['variants'][0]),
            )
        elif mode == 'workspaces':
            runner_class = FreshRunner if settings['branch_mode'] == 'fresh' else IncrementalRunner
            runner = runner_class(codex, repo, settings['workers'], task, iterations, log_root.name)
        else:
            runner = InPlaceRunner(codex, repo, task, iterations, resume=resume)
    return runner.run()


if __name__ == '__main__':
    main()
