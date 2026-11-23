import json
import runpy
import signal
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from agent_runner import runner
from agent_runner.codex import Codex, CodexResult, _create_mcp_server_options
from agent_runner.git import Git
from agent_runner.manifest import load_manifest
from agent_runner.runners.base import Runner
from agent_runner.runners.fresh import FreshRunner
from agent_runner.runners.in_place import InPlaceRunner
from agent_runner.runners.incremental import IncrementalRunner

from .utils import FIXTURES, read_json


INPUTS = FIXTURES / 'runner/input'


def test_cli_records_worker_and_iteration_overrides(tmp_path, monkeypatch):
    manifest = INPUTS / 'fresh.toml'
    settings = load_manifest(manifest)
    settings['log_root'] = str(tmp_path)
    monkeypatch.setattr(runner, 'load_manifest', Mock(return_value=settings))
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 0, 'head\n')))
    run_configured = Mock(return_value=True)
    monkeypatch.setattr(runner, '_run_configured', run_configured)

    result = CliRunner().invoke(
        runner.main, ['run', str(manifest), '--workers', '3', '--iterations', '5'],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stderr == ''
    metadata, = tmp_path.glob('*/metadata.json')
    agent = read_json(metadata)['settings']['agent']
    assert agent['workers'] == 3
    assert agent['iterations'] == 5
    run_configured.assert_called_once_with(
        {**settings, 'workers': 3, 'iterations': 5}, metadata.parent, False, 'workspaces',
    )


def test_cli_rejects_workers_outside_workspaces():
    result = CliRunner().invoke(
        runner.main, ['run', str(INPUTS / 'in_place.toml'), '--workers', '3'],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert '--workers requires workspaces mode' in result.stderr


@pytest.mark.parametrize(('case', 'exit_code', 'message'), (
    ('workspaces', 2, 'workspaces mode does not support --continue'),
    ('missing', 1, 'no run to continue under'),
    ('fewer_iterations', 2, 'agent.iterations cannot be less than the saved total'),
    ('different_settings', 1, 'manifest settings differ from the saved run'),
))
def test_cli_rejects_incompatible_resume(case, exit_code, message, tmp_path, monkeypatch):
    manifest = INPUTS / ('fresh.toml' if case == 'workspaces' else 'in_place.toml')
    settings = load_manifest(manifest)
    settings['log_root'] = str(tmp_path)
    record = tmp_path / 'saved' / 'run.toml'
    if case in ('fewer_iterations', 'different_settings'):
        record.parent.mkdir()
        record.touch()
    saved = settings.copy()
    if case == 'fewer_iterations':
        saved['iterations'] = 2
    elif case == 'different_settings':
        saved['model'] = 'another-model'
    monkeypatch.setattr(runner, 'load_manifest', {manifest: settings, record: saved}.__getitem__)

    result = CliRunner().invoke(runner.main, ['run', str(manifest), '--continue'], catch_exceptions=False)

    assert result.exit_code == exit_code
    assert message in result.stderr


def test_cli_creates_metadata_when_resuming_a_legacy_run(tmp_path, monkeypatch):
    manifest = INPUTS / 'in_place.toml'
    settings = load_manifest(manifest)
    settings['log_root'] = str(tmp_path)
    record = tmp_path / 'saved' / 'run.toml'
    record.parent.mkdir()
    record.touch()
    monkeypatch.setattr(runner, 'load_manifest', {manifest: settings, record: settings}.__getitem__)
    run_configured = Mock(return_value=True)
    monkeypatch.setattr(runner, '_run_configured', run_configured)

    result = CliRunner().invoke(runner.main, ['run', str(manifest), '--continue'], catch_exceptions=False)

    assert result.exit_code == 0
    assert read_json(record.parent / 'metadata.json')['settings']['log_root'] == '..'
    run_configured.assert_called_once_with(settings, record.parent, True, 'in-place')


def test_cli_records_missing_git_revision_and_depencity_version(tmp_path, monkeypatch):
    manifest = INPUTS / 'in_place.toml'
    settings = load_manifest(manifest)
    settings['log_root'] = str(tmp_path)
    monkeypatch.setattr(runner, 'load_manifest', Mock(return_value=settings))
    monkeypatch.setattr(runner, 'version', Mock(side_effect=PackageNotFoundError('depencity')))
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 1, '')))
    monkeypatch.setattr(runner, '_run_configured', Mock(return_value=True))

    result = CliRunner().invoke(runner.main, ['run', str(manifest)], catch_exceptions=False)

    assert result.exit_code == 0
    metadata, = tmp_path.glob('*/metadata.json')
    assert read_json(metadata)['depencity_version'] is None
    assert read_json(metadata)['commit_hash'] is None


def test_cli_reports_an_unreadable_task(monkeypatch):
    monkeypatch.setattr(runner, 'load_manifest', Mock(side_effect=OSError('cannot read task')))

    result = CliRunner().invoke(runner.main, ['run', str(INPUTS / 'in_place.toml')], catch_exceptions=False)

    assert result.exit_code == 1
    assert result.stderr == 'Error: cannot read task\n'


def test_cli_module_entry_point(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['agent-runner', '--help'])

    with pytest.raises(SystemExit) as exit_status:
        runpy.run_path(runner.__file__, run_name='__main__')

    assert exit_status.value.code == 0
    assert 'Run refactoring experiments defined by TOML manifests.' in capsys.readouterr().out


def test_codex_requires_an_executable(tmp_path, fake_which):
    fake_which.side_effect = None
    fake_which.return_value = None
    codex = Codex('model', tmp_path, INPUTS / 'build', 'Dockerfile.test')

    with pytest.raises(FileNotFoundError, match='codex CLI was not found'):
        codex.run('turn', INPUTS / 'repo', 'task')


def test_plain_codex_failure_returns_no_summary(tmp_path, monkeypatch, fake_which):
    run = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr(subprocess, 'run', run)
    codex = Codex('model', tmp_path, INPUTS / 'build', 'Dockerfile.test', with_depencity=False)

    assert codex.run('turn', INPUTS / 'repo', 'task') == CodexResult(7, '')
    args, = run.call_args.args
    assert 'mcp_servers.agent-runner.enabled_tools=["docker"]' in args
    assert all('mcp_servers.depencity.' not in arg for arg in args)
    fake_which.assert_called_once_with('codex')


def test_mcp_server_options_can_leave_the_tool_list_unspecified():
    options = _create_mcp_server_options('server', ['run'], INPUTS)

    assert options == [
        '--config', 'mcp_servers.server.command="uv"',
        '--config', 'mcp_servers.server.args=["run"]',
        '--config', f'mcp_servers.server.cwd={json.dumps(str(INPUTS))}',
        '--config', 'mcp_servers.server.default_tools_approval_mode="approve"',
    ]


def test_git_rejects_a_dirty_repository(monkeypatch):
    check_output = Mock(return_value=' M target.py\n')
    monkeypatch.setattr(subprocess, 'check_output', check_output)

    with pytest.raises(ValueError, match='repository must be clean'):
        Git(INPUTS / 'repo', 'run')

    check_output.assert_called_once_with(
        ['git', '-C', str(INPUTS / 'repo'), 'status', '--porcelain'],
        text=True, stderr=subprocess.PIPE,
    )


@pytest.mark.parametrize('runner_type', (FreshRunner, IncrementalRunner))
def test_worktree_runner_preserves_a_dirty_checkout_after_codex_failure(runner_type, monkeypatch, capsys):
    repo = INPUTS / 'repo'
    check_output = Mock(side_effect=['', 'revision\n', 'HEAD\n', '', ' M target.py\n'])
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    codex = Mock()
    codex.run.return_value = CodexResult(3, '')
    worktrees = runner_type(codex, repo, 1, 'task', 2, 'run')

    assert worktrees.run() is False
    assert codex.run.call_count == 1
    assert 'Preserving worktree with uncommitted changes' in capsys.readouterr().out
    assert all('remove' not in invocation.args[0] for invocation in check_output.call_args_list)


@pytest.mark.parametrize('runner_type', (FreshRunner, IncrementalRunner))
def test_worktree_runner_stops_after_first_turn(runner_type, monkeypatch):
    check_output = Mock(side_effect=['', 'revision\n', 'HEAD\n', '', '', '', ''])
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    codex = Mock()
    worktrees = runner_type(codex, INPUTS / 'repo', 1, 'task', 2, 'run')

    def finish_turn(*args):
        worktrees.handle_interrupt(signal.SIGINT, None)
        return CodexResult(0, 'done')

    codex.run.side_effect = finish_turn

    assert worktrees.run() is True
    assert codex.run.call_count == 1


@pytest.mark.parametrize('runner_type', (FreshRunner, IncrementalRunner))
def test_failed_codex_turn_does_not_schedule_another_clean_worktree(runner_type, monkeypatch):
    check_output = Mock(side_effect=['', 'revision\n', 'refs/heads/main\n', '', '', ''])
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    codex = Mock()
    codex.run.return_value = CodexResult(3, '')

    assert runner_type(codex, INPUTS / 'repo', 1, 'task', 2, 'run').run() is False
    assert codex.run.call_count == 1
    assert check_output.call_args.args[0][3:5] == ['worktree', 'remove']


def test_fresh_worktrees_reuse_detached_head_as_the_base(monkeypatch):
    check_output = Mock(side_effect=['', 'revision\n', 'HEAD\n', '', '', '', '', '', '', '', ''])
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    codex = Mock()
    codex.run.return_value = CodexResult(0, 'done')

    assert FreshRunner(codex, INPUTS / 'repo', 1, 'task', 2, 'run').run() is True
    args = [invocation.args[0][3:] for invocation in check_output.call_args_list]
    assert [command[-1] for command in args if command[:2] == ['worktree', 'add']] == [
        'revision', 'revision',
    ]
    assert args.count(['rev-parse', 'HEAD']) == 1


def test_runner_requires_a_worker_implementation():
    with pytest.raises(TypeError, match='abstract method.*run_worker'):
        Runner(Mock(), INPUTS / 'repo', 1, 'task', 1)


def test_second_interrupt_raises_keyboard_interrupt(capsys):
    in_place = InPlaceRunner(Mock(), INPUTS / 'repo', 'task', 2)

    in_place.handle_interrupt(signal.SIGINT, None)
    assert in_place.stopping
    assert 'Stopping after current runs' in capsys.readouterr().out
    with pytest.raises(KeyboardInterrupt):
        in_place.handle_interrupt(signal.SIGINT, None)


def test_in_place_stops_after_the_current_turn():
    codex = Mock()
    in_place = InPlaceRunner(codex, INPUTS / 'repo', 'task', 2)

    def finish_turn(*args):
        in_place.handle_interrupt(signal.SIGINT, None)
        return CodexResult(0, 'done')

    codex.run.side_effect = finish_turn
    assert in_place.run() is True
    assert codex.run.call_count == 1


def test_worker_errors_are_reported_without_escaping_the_runner(capsys):
    codex = Mock()
    codex.run.side_effect = OSError('unavailable')

    assert InPlaceRunner(codex, INPUTS / 'repo', 'task', 1).run() is False
    assert 'agent-01: stopped after runner error (unavailable)' in capsys.readouterr().out
