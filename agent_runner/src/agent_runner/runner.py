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
@click.option('--workers', type=click.IntRange(1, 100),
              help='Override agent.workers for workspaces mode.')
@click.option('--iterations', type=click.IntRange(1, 1000),
              help='Override agent.iterations. With --continue, this is the total.')
@cli_errors
def run(manifest: Path, resume: bool, workers: int | None, iterations: int | None) -> None:
    """Run MANIFEST, saving its resolved settings alongside the results."""
    settings = load_manifest(manifest)
    mode = settings['mode']
    if workers is not None:
        if mode != 'workspaces':
            raise click.UsageError('--workers requires workspaces mode')
        settings['workers'] = workers
    if iterations is not None:
        settings['iterations'] = iterations
    base = Path(settings['log_root'])
    log_root = _resolve_log_root(settings, base, resume, mode)
    _write_metadata(settings, log_root, resume)
    click.echo(f'Run: {log_root}')
    if not _run_configured(settings, log_root, resume, mode):
        raise click.exceptions.Exit(1)


def _resolve_log_root(settings, base, resume, mode):
    """Find the resumed run directory or create a new one."""
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
    return log_root


def _write_metadata(settings, log_root, resume):
    """Preserve run metadata while replacing its resolved settings."""
    metadata_path = log_root / 'metadata.json'
    if resume:
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    else:
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
    metadata['settings'] = recorded_settings(settings, log_root)
    pending = log_root / 'metadata.json.tmp'
    pending.write_text(json.dumps(metadata, indent=2) + '\n')
    pending.replace(metadata_path)


def _run_configured(settings, log_root, resume, mode) -> bool:
    """Build and execute the runner selected by the resolved settings."""
    if mode == 'evaluated':
        runner = _run_comparison if len(settings['variants']) > 1 else _run_evaluated
        return runner(settings, log_root, resume)
    if mode == 'workspaces':
        return _run_workspaces(settings, log_root)
    return _run_in_place(settings, log_root, resume)


def _docker_options(settings):
    return dict(build_root=Path(settings['build_root']), dockerfile=settings['dockerfile'])


def _run_comparison(settings, log_root, resume):
    """Run each evaluated variant in an isolated workspace."""
    repo = Path(settings['repo'])
    return ComparisonRunner(
        repo, log_root, settings['task'], settings['model'], settings['iterations'],
        Path(settings['target']), tuple(settings['metrics']), Path(settings['test_script']), resume,
        settings['reject_if_not_improved'], variants=settings['variants'], **_docker_options(settings),
    ).run()


def _run_evaluated(settings, log_root, resume):
    """Run one evaluated variant in its own workspace."""
    repo = Path(settings['repo'])
    directory = log_root / settings['variants'][0]
    directory.mkdir(parents=True, exist_ok=True)
    codex = _create_codex(settings, directory)
    runner = EvaluatedRunner(
        codex, repo, settings['task'], settings['iterations'], Path(settings['target']),
        tuple(settings['metrics']), Path(settings['test_script']), workspace=directory / 'workspace',
        resume=resume,
        reject_if_not_improved=settings['reject_if_not_improved'] in ('all', settings['variants'][0]),
    )
    return runner.run()


def _run_workspaces(settings, log_root):
    """Run concurrent workers in fresh or incremental worktrees."""
    repo = Path(settings['repo'])
    log_root.mkdir(parents=True, exist_ok=True)
    codex = _create_codex(settings, log_root)
    runner_class = FreshRunner if settings['branch_mode'] == 'fresh' else IncrementalRunner
    source_root = settings.get('source_root', '.')
    task = settings['task']
    if 'source_root' in settings:
        task += f' The source directory is {source_root}.'
    source_files = []
    for directory, subdirs, files in (repo / source_root).walk():
        subdirs[:] = [name for name in subdirs if not name.startswith('.') and name not in ('out', 'tests')]
        source_files.extend(
            (directory / name).relative_to(repo).as_posix()
            for name in files if name != '__init__.py' and name.endswith('.py') and not name.startswith(('.', 'test_'))
        )
    runner = runner_class(
        codex, repo, settings['workers'], task, settings['iterations'],
        log_root.name, sorted(source_files), settings.get('require_unchanged_coverage', False),
        settings.get('enforce_extraction_path_limits', False),
    )
    return runner.run()


def _run_in_place(settings, log_root, resume):
    """Run iterations directly in the repository."""
    log_root.mkdir(parents=True, exist_ok=True)
    codex = _create_codex(settings, log_root)
    return InPlaceRunner(codex, Path(settings['repo']), settings['task'], settings['iterations'], resume=resume).run()


def _create_codex(settings, directory):
    """Create a Codex client configured for the selected variant."""
    variants = settings.get('variants', ['depencity'])
    return Codex(
        settings['model'], directory,
        with_depencity=variants != ['plain'], source_root=settings.get('source_root', '.'),
        **_docker_options(settings),
    )


if __name__ == '__main__':
    main()
