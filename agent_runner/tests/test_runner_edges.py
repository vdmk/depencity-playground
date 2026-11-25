import json
import runpy
import signal
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from unittest.mock import MagicMock, Mock, call

import click
import pytest
from click.testing import CliRunner

from agent_runner import runner
from agent_runner.codex import Codex, CodexResult, _create_mcp_server_options
from agent_runner.git import Git
from agent_runner.manifest import load_manifest
from agent_runner.runners import worktree
from agent_runner.runners.base import Runner
from agent_runner.runners.fresh import FreshRunner
from agent_runner.runners.in_place import InPlaceRunner
from agent_runner.runners.incremental import IncrementalRunner

from .utils import FIXTURES, read_json


INPUTS = FIXTURES / 'runner/input'


@pytest.mark.parametrize(('missing_lines', 'missing_branches'), ((0, 0), (1, 0), (0, 1)))
@pytest.mark.parametrize('runner_type', (FreshRunner, IncrementalRunner))
def test_worktree_commits_only_at_baseline_coverage(
    missing_lines, missing_branches, runner_type, tmp_path, monkeypatch,
):
    checkout = tmp_path / 'checkout'
    candidate = tmp_path / 'candidate'
    branch = Mock(work_dir=candidate)
    git = Mock()
    context = MagicMock()
    context.__enter__.return_value = branch
    git.create_workspace_branch.return_value = context
    monkeypatch.setattr(worktree, 'Git', Mock(return_value=git))
    codex = Mock(log_dir=tmp_path, build_root=checkout, dockerfile='Dockerfile.test')
    codex.run.return_value = CodexResult(0, 'Simplify the workflow')

    def coverage_result(lines, branches):
        totals = {'missing_lines': lines, 'num_statements': 10,
                  'missing_branches': branches, 'num_branches': 4}
        output = 'tests passed\n' + json.dumps({'totals': totals})
        return json.dumps({'returncode': 0, 'output': output})

    unchanged = missing_lines == missing_branches == 0
    reports = [coverage_result(0, 0), coverage_result(missing_lines, missing_branches)]
    reports.append(coverage_result(0, 0))
    docker = Mock(side_effect=reports)
    monkeypatch.setattr(worktree, '_docker', docker)
    configured = runner_type(
        codex, checkout, 1, 'task', 2, 'run', require_unchanged_coverage=True,
    )

    assert configured.run() is True
    assert codex.run.call_count == 2
    assert codex.run.return_value.return_code == 0
    assert [invocation.args[1] for invocation in docker.call_args_list] == [checkout, candidate, candidate]
    assert len({invocation.args[4] for invocation in docker.call_args_list}) == 1
    assert (tmp_path / 'baseline.coverage.log').is_file()
    assert (tmp_path / 'agent-01.1.coverage.log').is_file()
    commit = call.commit('Simplify the workflow')
    assert branch.method_calls == [commit if unchanged else call.discard_candidate(), commit]


def test_worktree_does_not_start_workers_when_baseline_coverage_fails(tmp_path, monkeypatch):
    git = Mock()
    monkeypatch.setattr(worktree, 'Git', Mock(return_value=git))
    docker = Mock(return_value=json.dumps({'returncode': 1, 'output': 'tests failed\n'}))
    monkeypatch.setattr(worktree, '_docker', docker)
    codex = Mock(log_dir=tmp_path, build_root=tmp_path, dockerfile='Dockerfile.test')
    configured = IncrementalRunner(
        codex, tmp_path, 1, 'task', 1, 'run', require_unchanged_coverage=True,
    )

    with pytest.raises(click.ClickException, match='baseline: coverage check failed'):
        configured.run()

    docker.assert_called_once()
    git.create_workspace_branch.assert_not_called()
    codex.run.assert_not_called()
    assert (tmp_path / 'baseline.coverage.log').read_text() == 'tests failed\n'


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


@pytest.mark.parametrize(('branch_mode', 'runner_type'), (
    ('fresh', FreshRunner), ('incremental', IncrementalRunner),
))
def test_workspaces_keep_disjoint_file_assignments(branch_mode, runner_type, tmp_path, monkeypatch):
    source = tmp_path / 'src'
    source.mkdir()
    (tmp_path / 'outside.py').touch()
    for name in ('a.py', 'b.py', 'c.py', 'd.py', '.hidden.py', 'notes.txt'):
        (source / name).touch()
    hidden = source / '.cache'
    hidden.mkdir()
    (hidden / 'ignored.py').touch()
    output = source / 'out'
    output.mkdir()
    (output / 'generated.py').touch()
    tests = source / 'tests'
    tests.mkdir()
    (tests / 'helpers.py').touch()
    manifest = tmp_path / 'run.toml'
    manifest.write_text(
        (INPUTS / f'{branch_mode}.toml').read_text()
        .replace('build_root = "build"', f'build_root = "{INPUTS / "build"}"')
        .replace('task_file = "task.txt"', 'task = "Refactor source."')
        .replace('workers = 1', 'workers = 2')
        .replace('[agent]', 'source_root = "src"\n\n[agent]')
    )
    check_output = Mock(side_effect=['', 'head', 'refs/heads/main'])
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 0, 'head\n')))
    codex = Mock()
    codex.run.return_value = CodexResult(0, 'done')
    create_codex = Mock(return_value=codex)
    monkeypatch.setattr(runner, 'Codex', create_codex)

    def run_assigned_turns(selected):
        for name in ('agent-01', 'agent-02'):
            for iteration in (1, 2):
                selected.run_iteration(name, iteration, tmp_path)
        return True

    monkeypatch.setattr(runner_type, 'run', run_assigned_turns)
    result = CliRunner().invoke(runner.main, ['run', str(manifest)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert create_codex.call_args.kwargs['source_root'] == 'src'
    assert 'The source directory is src.' in codex.run.call_args.args[2]
    git_options = {'text': True, 'stderr': subprocess.PIPE}
    assert check_output.call_args_list == [
        call(['git', '-C', str(tmp_path), 'status', '--porcelain'], **git_options),
        call(['git', '-C', str(tmp_path), 'rev-parse', 'HEAD'], **git_options),
        call(['git', '-C', str(tmp_path), 'rev-parse', '--symbolic-full-name', 'HEAD'], **git_options),
    ]
    assert [
        (invocation.args[0], invocation.args[2].split('Refactor only these source files, in order: ')[1])
        for invocation in codex.run.call_args_list
    ] == [
        ('agent-01.1', 'src/a.py, src/c.py.'),
        ('agent-01.2', 'src/a.py, src/c.py.'),
        ('agent-02.1', 'src/b.py, src/d.py.'),
        ('agent-02.2', 'src/b.py, src/d.py.'),
    ]


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


def test_codex_grants_writes_only_under_the_configured_source_root(tmp_path, monkeypatch, fake_which):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    source = checkout / 'src'
    source.mkdir()
    run = Mock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr(subprocess, 'run', run)
    codex = Codex('model', tmp_path, INPUTS / 'build', 'Dockerfile.test', source_root='src')

    assert codex.run('turn', checkout, 'task').return_code == 7
    args, = run.call_args.args
    rule, = (arg for arg in args if arg.startswith('permissions.project.filesystem='))
    assert f'{json.dumps(str(checkout))} = "read"' in rule
    assert f'{json.dumps(str(source))} = "write"' in rule
    assert rule.count('= "write"') == 1


@pytest.mark.parametrize('source_root', ('/outside', 'link'))
def test_codex_rejects_source_roots_that_escape_the_checkout(source_root, tmp_path, monkeypatch, fake_which):
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    (checkout / 'link').symlink_to(tmp_path, target_is_directory=True)
    run = Mock()
    monkeypatch.setattr(subprocess, 'run', run)
    codex = Codex('model', tmp_path, INPUTS / 'build', 'Dockerfile.test', source_root=source_root)

    with pytest.raises(ValueError, match='source_root must resolve directly inside the worker checkout'):
        codex.run('turn', checkout, 'task')

    run.assert_not_called()


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
