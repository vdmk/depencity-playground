"""Create TOML experiment definitions for orchestration integration tests."""

import json
import tempfile
import tomllib
from pathlib import Path

from click.testing import CliRunner

from agent_runner.runner import main


TABLES = {
    'agent': {'model': 'model', 'iterations': 'iterations', 'workers': 'workers'},
    'evaluation': {'target': 'target', 'test_script': 'test_script', 'metrics': 'metrics',
                   'depencity_accept': 'acceptance'},
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
            for table, mapping in TABLES.items():
                saved.update({key: data[table][field] for key, field in mapping.items()
                              if field in data.get(table, {})})
    settings = {'name': 'integration-test', **saved, **settings}
    settings.setdefault('repo', str(repo))
    settings['repo'] = str(Path(settings['repo']).resolve())
    fields = {key for mapping in TABLES.values() for key in mapping}
    lines = [f'{key} = {json.dumps(value)}' for key, value in settings.items() if key not in fields]
    for table, mapping in TABLES.items():
        values = [f'{field} = {json.dumps(settings[key])}'
                  for key, field in mapping.items() if key in settings]
        if values:
            lines.extend(['', f'[{table}]', *values])
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / 'experiment.toml'
        manifest.write_text('\n'.join(lines) + '\n')
        return CliRunner().invoke(main, ['run', str(manifest), *(['--continue'] if resume else [])])
