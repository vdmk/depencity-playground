"""Read experiment definitions and write self-contained resolved TOML manifests."""

import json
import tomllib
from pathlib import Path

import click


DEFAULT_TASK = (
    'Make one coherent, behavior-preserving refactoring. Follow repository '
    'guidance and run relevant tests.'
)

# Fields belonging to each TOML table.
TABLES = {
    'agent': ('model', 'iterations', 'workers'),
    'evaluation': ('target', 'test_script', 'metrics', 'reject_if_not_improved'),
}


def load_manifest(path: Path) -> dict:
    """Resolve paths from the manifest directory, and evaluation paths from repo."""
    path = path.resolve()
    data = tomllib.loads(path.read_text())
    unknown = data.keys() - {'name', 'mode', 'repo', 'log_root', 'task', 'task_file', 'branch_mode', 'variants', *TABLES}
    if unknown:
        raise click.UsageError(f'unknown manifest keys: {", ".join(sorted(unknown))}')
    settings = dict(name=path.parent.name, mode='in-place', repo='.', task=DEFAULT_TASK,
                    model='gpt-6-luna', iterations=1)
    for key in ('name', 'mode', 'repo', 'log_root', 'task'):
        if key in data:
            if not isinstance(data[key], str) or not data[key].strip():
                raise click.UsageError(f'{key} must be a nonempty string')
            settings[key] = data[key]
    if 'log_root' not in settings:
        raise click.UsageError('manifest requires log_root')
    mode = settings['mode']
    if mode not in ('in-place', 'evaluated', 'workspaces'):
        raise click.UsageError('mode must be in-place, evaluated, or workspaces')
    if 'variants' in data and mode != 'evaluated':
        raise click.UsageError('variants requires evaluated mode')
    if mode == 'evaluated':
        variants = data.get('variants', ['depencity'])
        if (not isinstance(variants, list) or not variants
                or any(variant not in ('depencity', 'plain') for variant in variants)
                or len(set(variants)) != len(variants)):
            raise click.UsageError('variants must be a nonempty array of unique depencity or plain names')
        settings['variants'] = variants
    allowed = {'agent'}
    if mode == 'evaluated':
        allowed.add('evaluation')
        settings.update(metrics=['graph.paths.expressions.count'], reject_if_not_improved=False)
    if mode == 'workspaces':
        settings.update(workers=5, branch_mode='fresh')
    if 'branch_mode' in data:
        if mode != 'workspaces':
            raise click.UsageError('branch_mode requires workspaces mode')
        settings['branch_mode'] = data['branch_mode']
    for table, fields in TABLES.items():
        if table not in data:
            continue
        if table not in allowed or not isinstance(data[table], dict):
            raise click.UsageError(f'{table} is not supported in {mode} mode')
        unknown = data[table].keys() - set(fields)
        if unknown:
            raise click.UsageError(f'unknown {table} keys: {", ".join(sorted(unknown))}')
        for key, value in data[table].items():
            if key == 'workers' and mode != 'workspaces':
                raise click.UsageError(f'agent.{key} requires workspaces mode')
            settings[key] = value
    for key, limit in (('iterations', 1000), ('workers', 100)):
        if key in settings and (type(settings[key]) is not int or not 1 <= settings[key] <= limit):
            raise click.UsageError(f'agent.{key} must be an integer between 1 and {limit}')
    if 'branch_mode' in settings and settings['branch_mode'] not in ('fresh', 'incremental'):
        raise click.UsageError('branch_mode must be fresh or incremental')
    if not isinstance(settings['model'], str) or not settings['model'].strip():
        raise click.UsageError('agent.model must be a nonempty string')
    if 'task_file' in data:
        if 'task' in data:
            raise click.UsageError('use task or task_file, not both')
        if not isinstance(data['task_file'], str) or not data['task_file'].strip():
            raise click.UsageError('task_file must be a nonempty string')
        settings['task'] = (path.parent / data['task_file']).read_text()
        if not settings['task'].strip():
            raise click.UsageError('task_file must contain a task')
    for key in ('repo', 'log_root'):
        settings[key] = str((path.parent / settings[key]).resolve())
    repo = Path(settings['repo'])
    if not repo.is_dir():
        raise click.UsageError(f'repo is not a directory: {repo}')
    if mode == 'evaluated':
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
    return settings


def save_manifest(path: Path, settings: dict) -> None:
    """Save effective settings with absolute paths and the complete prompt text."""
    lines = [f'{key} = {json.dumps(settings[key], ensure_ascii=False)}'
             for key in ('name', 'mode', 'repo', 'log_root', 'task')]
    for key in ('branch_mode', 'variants'):
        if key in settings:
            lines.append(f'{key} = {json.dumps(settings[key])}')
    for table, fields in TABLES.items():
        values = [f'{key} = {json.dumps(settings[key], ensure_ascii=False)}'
                  for key in fields if key in settings]
        if values:
            lines.extend(['', f'[{table}]', *values])
    path.write_text('\n'.join(lines) + '\n')
