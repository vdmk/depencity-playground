import json
import re

import click
import pytest

from agent_runner.manifest import DEFAULT_TASK, latest_record, load_manifest

from .utils import FIXTURES


INPUTS = FIXTURES / 'runner/input'


@pytest.mark.parametrize(('settings', 'tables', 'message'), (
    ({'extra': 'true'}, '', 'unknown manifest keys: extra'),
    ({'name': '42'}, '', 'name must be a nonempty string'),
    ({'name': '" "'}, '', 'name must be a nonempty string'),
    ({'mode': '"parallel"'}, '', 'mode must be in-place, evaluated, or workspaces'),
    ({'variants': '["plain"]'}, '', 'variants requires evaluated mode'),
    ({'mode': '"evaluated"', 'variants': '"plain"'}, '', 'variants must be a nonempty array'),
    ({'mode': '"evaluated"', 'variants': '[]'}, '', 'variants must be a nonempty array'),
    ({'mode': '"evaluated"', 'variants': '["unknown"]'}, '', 'variants must be a nonempty array'),
    ({'mode': '"evaluated"', 'variants': '["plain", "plain"]'}, '', 'variants must be a nonempty array'),
    ({'branch_mode': '"fresh"'}, '', 'branch_mode requires workspaces mode'),
    ({'source_root': '"src"'}, '', 'source_root requires workspaces mode'),
    ({'mode': '"workspaces"', 'source_root': '1'}, '', 'source_root must be a repository-relative directory'),
    ({'mode': '"workspaces"', 'source_root': '" "'}, '', 'source_root must be a repository-relative directory'),
    ({'mode': '"workspaces"', 'source_root': '"/src"'}, '', 'source_root must be a repository-relative directory'),
    ({'mode': '"workspaces"', 'source_root': '".."'}, '', 'source_root must be a directory inside the repository'),
    ({'mode': '"workspaces"', 'source_root': '"missing"'}, '', 'source_root must be a directory inside the repository'),
    ({'mode': '"workspaces"', 'branch_mode': '"other"'}, '', 'branch_mode must be fresh or incremental'),
    ({'agent': '1'}, '', 'agent is not supported in in-place mode'),
    ({}, '[evaluation]\ntarget = "target.py"', 'evaluation is not supported in in-place mode'),
    ({}, '[agent]\nunknown = 1', 'unknown agent keys: unknown'),
    ({}, '[agent]\nworkers = 1', 'agent.workers requires workspaces mode'),
    ({}, '[agent]\nrequire_unchanged_coverage = true', 'agent.require_unchanged_coverage requires workspaces mode'),
    ({'mode': '"workspaces"'}, '[agent]\nrequire_unchanged_coverage = 1',
     'agent.require_unchanged_coverage must be a boolean'),
    ({}, '[agent]\niterations = true', 'agent.iterations must be an integer'),
    ({'mode': '"workspaces"'}, '[agent]\nworkers = 101', 'agent.workers must be an integer'),
    ({}, '[agent]\niterations = 0', 'agent.iterations must be an integer'),
    ({}, '[agent]\nmodel = 1', 'agent.model must be a nonempty string'),
    ({}, '[agent]\nmodel = " "', 'agent.model must be a nonempty string'),
    ({'task': '"change this"', 'task_file': '"task.txt"'}, '', 'use task or task_file, not both'),
    ({'task_file': 'true'}, '', 'task_file must be a nonempty string'),
    ({'task_file': '""'}, '', 'task_file must be a nonempty string'),
    ({'task_file': '"blank.txt"'}, '', 'task_file must contain a task'),
    ({'build_root': None}, '', 'manifest requires build_root'),
    ({'dockerfile': None}, '', 'manifest requires dockerfile'),
    ({'repo': '"missing"'}, '', 'repo is not a directory'),
    ({'dockerfile': '"missing"'}, '', 'dockerfile must be an existing file inside build_root'),
    ({'dockerfile': '"../task.txt"'}, '', 'dockerfile must be an existing file inside build_root'),
))
def test_manifest_rejects_invalid_settings(settings, tables, message, tmp_path):
    if settings.get('task_file') == '"blank.txt"':
        (tmp_path / 'blank.txt').write_text(' \n')
    manifest = tmp_path / 'run.toml'
    fields = {
        'repo': json.dumps(str(INPUTS / 'repo')),
        'log_root': '"logs"',
        'build_root': json.dumps(str(INPUTS / 'build')),
        'dockerfile': '"Dockerfile.test"',
    } | settings
    manifest.write_text('\n'.join(f'{key} = {value}' for key, value in fields.items() if value is not None)
                        + '\n' + tables)

    with pytest.raises(click.UsageError, match=re.escape(message)):
        load_manifest(manifest)


@pytest.mark.parametrize(('evaluation', 'message'), (
    ({'target': None}, 'evaluation requires target and test_script'),
    ({'target': '""'}, 'evaluation requires target and test_script'),
    ({'target': '"../task.txt"'}, 'evaluation.target must be inside repo'),
    ({'target': '"missing.py"'}, 'evaluation.target is not a file'),
    ({'test_script': '"target.py"'}, 'evaluation.target and test_script must be different files'),
    ({'metrics': '"some.metric"'}, 'evaluation.metrics must be a nonempty array'),
    ({'metrics': '[]'}, 'evaluation.metrics must be a nonempty array'),
    ({'metrics': '[" "]'}, 'evaluation.metrics must be a nonempty array'),
    ({'metrics': '[1]'}, 'evaluation.metrics must be a nonempty array'),
    ({'metrics': '["some.metric", "some.metric"]'}, 'evaluation.metrics must be a nonempty array'),
    ({'reject_if_not_improved': '"plain"'}, 'evaluation.reject_if_not_improved must be false, depencity, or all'),
))
def test_manifest_rejects_invalid_evaluation_settings(evaluation, message, tmp_path):
    manifest = tmp_path / 'run.toml'
    fields = {'target': '"target.py"', 'test_script': '"test_target.py"'} | evaluation
    manifest.write_text(
        'mode = "evaluated"\nlog_root = "logs"\ndockerfile = "Dockerfile.test"\n'
        f'repo = {json.dumps(str(INPUTS / "repo"))}\n'
        f'build_root = {json.dumps(str(INPUTS / "build"))}\n[evaluation]\n'
        + '\n'.join(f'{key} = {value}' for key, value in fields.items() if value is not None)
    )

    with pytest.raises(click.UsageError, match=re.escape(message)):
        load_manifest(manifest)


def test_manifest_resolves_default_task_and_evaluation(tmp_path):
    manifest = tmp_path / 'run.toml'
    manifest.write_text(
        'mode = "evaluated"\nlog_root = "logs"\ndockerfile = "Dockerfile.test"\n'
        f'repo = {json.dumps(str(INPUTS / "repo"))}\n'
        f'build_root = {json.dumps(str(INPUTS / "build"))}\n[evaluation]\n'
        'target = "target.py"\ntest_script = "test_target.py"\n'
    )

    settings = load_manifest(manifest)

    assert settings['task'] == DEFAULT_TASK
    assert settings['variants'] == ['depencity']
    assert settings['reject_if_not_improved'] is False
    assert settings['log_root'] == str(tmp_path / 'logs')


def test_latest_record_ignores_incomplete_runs_and_accepts_legacy_record(tmp_path):
    incomplete = tmp_path / '20260102'
    incomplete.mkdir()
    (incomplete / 'metadata.json').write_text('{}')
    older = tmp_path / '20260101'
    older.mkdir()

    assert latest_record(tmp_path) is None

    (older / 'run.toml').touch()
    assert latest_record(tmp_path) == older / 'run.toml'

    (older / 'metadata.json').write_text('{"settings": {}}')
    assert latest_record(tmp_path) == older / 'metadata.json'
