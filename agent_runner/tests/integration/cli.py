"""Create TOML experiment definitions for orchestration integration tests."""

import json
import tempfile
import tomllib
from pathlib import Path

from click.testing import CliRunner

from agent_runner.runner import main


TABLES = {
    'agent': ('model', 'iterations', 'workers'),
    'evaluation': ('target', 'test_script', 'metrics', 'reject_if_not_improved'),
}


def invoke_manifest(settings):
    settings = settings.copy()
    resume = settings.pop('resume', False)
    repo = Path(settings.get('repo', '.')).resolve()
    if 'log_root' in settings:
        settings['log_root'] = str((repo / settings['log_root']).resolve())
    saved = {}
    if resume:
        manifests = sorted(Path(settings['log_root']).glob('*/run.toml'))
        if manifests:
            data = tomllib.loads(manifests[-1].read_text())
            saved = {key: value for key, value in data.items() if key not in TABLES}
            for table, fields in TABLES.items():
                saved.update({key: data[table][key] for key in fields
                              if key in data.get(table, {})})
    settings = {'name': 'integration-test', **saved, **settings}
    settings.setdefault('repo', str(repo))
    settings['repo'] = str(Path(settings['repo']).resolve())
    fields = {key for table_fields in TABLES.values() for key in table_fields}
    lines = [f'{key} = {json.dumps(value)}' for key, value in settings.items() if key not in fields]
    for table, fields in TABLES.items():
        values = [f'{key} = {json.dumps(settings[key])}'
                  for key in fields if key in settings]
        if values:
            lines.extend(['', f'[{table}]', *values])
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / 'experiment.toml'
        manifest.write_text('\n'.join(lines) + '\n')
        return CliRunner().invoke(main, ['run', str(manifest), *(['--continue'] if resume else [])])
