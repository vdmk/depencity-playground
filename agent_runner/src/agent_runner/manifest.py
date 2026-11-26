"""Read experiment definitions and record effective run settings."""

import json
import os
import tomllib
from pathlib import Path

import click


DEFAULT_TASK = (
    'Make one coherent, behavior-preserving refactoring. Follow repository '
    'guidance and run relevant tests.'
)

# Fields belonging to each TOML table.
TABLES = {
    'agent': ('model', 'iterations', 'workers', 'require_unchanged_coverage', 'enforce_extraction_path_limits'),
    'evaluation': ('target', 'test_script', 'metrics', 'reject_if_not_improved'),
}


def load_manifest(path: Path) -> dict:
    """Resolve paths from the manifest directory, and evaluation paths from repo."""
    path = path.resolve()
    data = _read_manifest(path)
    settings = _default_settings(path)
    allowed = _configure_mode(settings, data)
    _apply_manifest_values(settings, data, allowed)
    _validate_agent_settings(settings)
    _read_task_file(settings, data, path)
    _resolve_build_paths(settings, path)
    repo = Path(settings['repo'])
    _resolve_source_root(settings, data, repo)
    if settings['mode'] == 'evaluated':
        _resolve_evaluation_paths(settings, repo)
    return settings


def _resolve_source_root(settings: dict, data: dict, repo: Path) -> None:
    """Validate and normalize the optional workspace source directory."""
    if 'source_root' not in data:
        return
    if settings['mode'] != 'workspaces':
        raise click.UsageError('source_root requires workspaces mode')
    value = data['source_root']
    if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
        raise click.UsageError('source_root must be a repository-relative directory')
    source_root = (repo / value).resolve()
    if not source_root.is_relative_to(repo) or not source_root.is_dir():
        raise click.UsageError('source_root must be a directory inside the repository')
    settings['source_root'] = source_root.relative_to(repo).as_posix()


def _read_manifest(path: Path) -> dict:
    """Read a TOML manifest or the settings saved in run metadata."""
    if path.name == 'metadata.json':
        data = json.loads(path.read_text())['settings']
    else:
        data = tomllib.loads(path.read_text())
    unknown = data.keys() - {'name', 'mode', 'repo', 'log_root', 'task', 'task_file', 'build_root', 'dockerfile', 'branch_mode', 'source_root', 'variants', *TABLES}
    if unknown:
        raise click.UsageError(f'unknown manifest keys: {", ".join(sorted(unknown))}')
    return data


def _default_settings(path: Path) -> dict:
    """Create settings with the defaults shared by all manifest modes."""
    return dict(name=path.parent.name, mode='in-place', repo='.', task=DEFAULT_TASK,
                model='gpt-6-luna', iterations=1)


def _configure_mode(settings: dict, data: dict) -> set[str]:
    """Validate mode-specific options and install their defaults."""
    for key in ('name', 'mode', 'repo', 'log_root', 'task', 'build_root', 'dockerfile'):
        if key in data:
            if not isinstance(data[key], str) or not data[key].strip():
                raise click.UsageError(f'{key} must be a nonempty string')
            settings[key] = data[key]
    if 'log_root' not in settings:
        raise click.UsageError('manifest requires log_root')
    mode = settings['mode']
    if mode not in ('in-place', 'evaluated', 'workspaces'):
        raise click.UsageError('mode must be in-place, evaluated, or workspaces')
    _validate_mode_options(data, mode)
    allowed = {'agent'}
    if mode == 'evaluated':
        _configure_evaluated(settings, data)
        allowed.add('evaluation')
        settings.update(metrics=['graph.paths.expressions.count'], reject_if_not_improved=False)
    if 'branch_mode' in data and mode != 'workspaces':
        raise click.UsageError('branch_mode requires workspaces mode')
    if mode == 'workspaces':
        _configure_workspaces(settings, data)
    return allowed


def _validate_mode_options(data: dict, mode: str) -> None:
    """Reject options that do not apply to the selected mode."""
    if 'variants' in data and mode != 'evaluated':
        raise click.UsageError('variants requires evaluated mode')


def _configure_evaluated(settings: dict, data: dict) -> None:
    """Validate and install evaluated-mode variants."""
    variants = data.get('variants', ['depencity'])
    if (not isinstance(variants, list) or not variants
            or any(variant not in ('depencity', 'plain') for variant in variants)
            or len(set(variants)) != len(variants)):
        raise click.UsageError('variants must be a nonempty array of unique depencity or plain names')
    settings['variants'] = variants


def _configure_workspaces(settings: dict, data: dict) -> None:
    """Install workspace defaults and an optional branch mode."""
    settings.update(workers=5, branch_mode='fresh')
    if 'branch_mode' in data:
        settings['branch_mode'] = data['branch_mode']


def _apply_manifest_values(settings: dict, data: dict, allowed: set[str]) -> None:
    """Apply table values after validating they are supported in this mode."""
    mode = settings['mode']
    for table, fields in TABLES.items():
        if table not in data:
            continue
        values = data[table]
        if table not in allowed or not isinstance(values, dict):
            raise click.UsageError(f'{table} is not supported in {mode} mode')
        unknown = values.keys() - set(fields)
        if unknown:
            raise click.UsageError(f'unknown {table} keys: {", ".join(sorted(unknown))}')
        for key, value in values.items():
            if (key in ('workers', 'require_unchanged_coverage', 'enforce_extraction_path_limits')
                    and mode != 'workspaces'):
                raise click.UsageError(f'agent.{key} requires workspaces mode')
            elif (key in ('require_unchanged_coverage', 'enforce_extraction_path_limits')
                  and not isinstance(value, bool)):
                raise click.UsageError(f'agent.{key} must be a boolean')
            settings[key] = value


def _validate_agent_settings(settings: dict) -> None:
    """Validate generic limits and options that apply to every runner mode."""
    for key, limit in (('iterations', 1000), ('workers', 100)):
        if key in settings and (type(settings[key]) is not int or not 1 <= settings[key] <= limit):
            raise click.UsageError(f'agent.{key} must be an integer between 1 and {limit}')
    if 'branch_mode' in settings and settings['branch_mode'] not in ('fresh', 'incremental'):
        raise click.UsageError('branch_mode must be fresh or incremental')
    if not isinstance(settings['model'], str) or not settings['model'].strip():
        raise click.UsageError('agent.model must be a nonempty string')


def _read_task_file(settings: dict, data: dict, path: Path) -> None:
    """Resolve task_file when supplied and reject conflicting task sources."""
    if 'task_file' not in data:
        return
    if 'task' in data:
        raise click.UsageError('use task or task_file, not both')
    task_file = data['task_file']
    if not isinstance(task_file, str) or not task_file.strip():
        raise click.UsageError('task_file must be a nonempty string')
    settings['task'] = (path.parent / task_file).read_text()
    if not settings['task'].strip():
        raise click.UsageError('task_file must contain a task')


def _resolve_build_paths(settings: dict, path: Path) -> None:
    """Resolve repository and Docker paths and validate the Dockerfile."""
    for key in ('build_root', 'dockerfile'):
        if key not in settings:
            raise click.UsageError(f'manifest requires {key}')
    for key in ('repo', 'log_root', 'build_root'):
        settings[key] = str((path.parent / settings[key]).resolve())
    repo = Path(settings['repo'])
    if not repo.is_dir():
        raise click.UsageError(f'repo is not a directory: {repo}')
    build_root = Path(settings['build_root'])
    dockerfile = (build_root / settings['dockerfile']).resolve()
    if not dockerfile.is_relative_to(build_root) or not dockerfile.is_file():
        raise click.UsageError('dockerfile must be an existing file inside build_root')
    settings['dockerfile'] = str(dockerfile.relative_to(build_root))


def _resolve_evaluation_paths(settings: dict, repo: Path) -> None:
    """Resolve evaluation files and validate evaluation-only settings."""
    for key in ('target', 'test_script'):
        if not isinstance(settings.get(key), str) or not settings[key].strip():
            raise click.UsageError('evaluation requires target and test_script')
        source = (repo / settings[key]).resolve()
        try:
            settings[key] = str(source.relative_to(repo))
        except ValueError as error:
            raise click.UsageError(f'evaluation.{key} must be inside repo') from error
        if not source.is_file():
            raise click.UsageError(f'evaluation.{key} is not a file: {source}')
    if settings['target'] == settings['test_script']:
        raise click.UsageError('evaluation.target and test_script must be different files')
    metrics = settings['metrics']
    if (not isinstance(metrics, list) or not metrics
            or any(not isinstance(metric, str) or not metric.strip() for metric in metrics)
            or len(set(metrics)) != len(metrics)):
        raise click.UsageError('evaluation.metrics must be a nonempty array of unique metric names')
    if (settings['reject_if_not_improved'] is not False
            and settings['reject_if_not_improved'] not in ('all', 'depencity')):
        raise click.UsageError('evaluation.reject_if_not_improved must be false, depencity, or all')


def recorded_settings(settings: dict, directory: Path) -> dict:
    fields = {key for keys in TABLES.values() for key in keys}
    record = {key: value for key, value in settings.items() if key not in fields}
    for key in ('repo', 'log_root', 'build_root'):
        record[key] = os.path.relpath(settings[key], directory)
    for table, keys in TABLES.items():
        values = {key: settings[key] for key in keys if key in settings}
        if values:
            record[table] = values
    return record


def latest_record(base: Path):
    for directory in sorted(base.glob('*/'), reverse=True):
        metadata = directory / 'metadata.json'
        if metadata.is_file() and 'settings' in json.loads(metadata.read_text()):
            return metadata
        legacy = directory / 'run.toml'
        if legacy.is_file():
            return legacy
    return None
