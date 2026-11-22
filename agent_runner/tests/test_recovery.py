import json
import subprocess
from pathlib import Path
from unittest.mock import ANY, Mock, create_autospec

import pytest
from click.testing import CliRunner

from agent_runner import evaluator, runner
from agent_runner.codex import CodexResult
from agent_runner.evaluator import Evaluator, checked_workspace_path
from agent_runner.runners.comparison import ComparisonRunner
from agent_runner.runners.evaluated import EvaluatedRunner

from .utils import FIXTURES, read_json


INPUTS = FIXTURES / 'runner/input'
METRIC = 'graph.paths.expressions.count'
ORIGINAL = (INPUTS / 'repo/target.py').read_bytes()
CANDIDATE = b'answer = 42\n'
RUN_ID = '20260102T030405000000Z-42'
pytestmark = pytest.mark.usefixtures('fixed_runner_metadata')


@pytest.mark.parametrize('path', ('../outside.py', '/outside.py'))
def test_workspace_rejects_paths_outside_the_root(path, tmp_path):
    with pytest.raises(OSError, match='path must be relative to workspace'):
        checked_workspace_path(tmp_path, path)


def test_workspace_rejects_symlinks_and_directories(tmp_path):
    (tmp_path / 'link').symlink_to(INPUTS / 'repo/target.py')
    (tmp_path / 'directory').mkdir()

    with pytest.raises(OSError, match='workspace symlinks are not allowed'):
        checked_workspace_path(tmp_path, 'link')
    with pytest.raises(OSError, match='workspace file must be regular'):
        checked_workspace_path(tmp_path, 'directory')


def test_profile_requires_a_root_scope(monkeypatch, fake_which):
    probe = Evaluator(INPUTS / 'repo', 'target.py', (METRIC,), 'test_target.py',
                      True, INPUTS / 'build', 'Dockerfile.test')
    result = subprocess.CompletedProcess([], 0, '{"scopes":[{"id":"function"}]}')
    monkeypatch.setattr(subprocess, 'run', Mock(return_value=result))

    with pytest.raises(ValueError, match='no root profile'):
        probe.measure()


@pytest.mark.parametrize('failed_report', (False, True))
def test_evaluated_runner_restores_saved_turns_before_retrying(tmp_path, monkeypatch, failed_report):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'target.py').write_bytes(b'interrupted contents\n')
    saved_test = b'def test_original(): assert True\n'
    (workspace / 'test_target.py').write_bytes(saved_test)
    for iteration, status, suffix in ((1, 'accepted', 'candidate'), (2, 'rejected', 'before')):
        (tmp_path / f'agent-01.{iteration}.evaluation.json').write_text(
            json.dumps({'status': status, 'accepted': status == 'accepted'}),
        )
        (tmp_path / f'agent-01.{iteration}.{suffix}.py').write_bytes(CANDIDATE)
    (tmp_path / 'agent-01.3.before.py').write_bytes(ORIGINAL)
    if failed_report:
        (tmp_path / 'agent-01.3.evaluation.json').write_text('{"status":"agent_failed"}')

    codex = Mock(log_dir=tmp_path, build_root=INPUTS / 'build', dockerfile='Dockerfile.test')

    def failed_turn(name, directory, task):
        assert (directory / 'target.py').read_bytes() == ORIGINAL
        assert (directory / 'test_target.py').read_bytes() == saved_test
        (directory / 'target.py').write_bytes(b'failed edit\n')
        return CodexResult(7, '')

    codex.run.side_effect = failed_turn
    measure = Mock(return_value={METRIC: 4})
    monkeypatch.setattr(Evaluator, 'measure', measure)
    run = EvaluatedRunner(codex, INPUTS / 'repo', 'task', 4, 'target.py', (METRIC,),
                          'test_target.py', workspace, resume=True, reject_if_not_improved=True)

    assert run.run() is False
    codex.run.assert_called_once_with('agent-01.3', ANY, run.task)
    assert (workspace / 'target.py').read_bytes() == ORIGINAL
    assert read_json(tmp_path / 'agent-01.3.evaluation.json')['status'] == 'agent_failed'


@pytest.mark.parametrize('docker_fails', (False, True))
def test_evaluated_runner_handles_interrupt_or_restores_after_test_launch_error(
    tmp_path, monkeypatch, docker_fails,
):
    workspace = tmp_path / 'workspace'
    codex = Mock(log_dir=tmp_path, build_root=INPUTS / 'build', dockerfile='Dockerfile.test')
    run = EvaluatedRunner(codex, INPUTS / 'repo', 'task', 2, 'target.py', (METRIC,),
                          'test_target.py', workspace, resume=False, reject_if_not_improved=False)

    def finish_turn(name, directory, task):
        (directory / 'target.py').write_bytes(CANDIDATE)
        run.handle_interrupt(None, None)
        return CodexResult(0, 'done')

    codex.run.side_effect = finish_turn
    measure = Mock(side_effect=[{METRIC: 4}, {METRIC: 5}])
    docker = (Mock(side_effect=OSError('cannot start tests')) if docker_fails
              else Mock(return_value='{"returncode":0,"output":"passed"}'))
    monkeypatch.setattr(Evaluator, 'measure', measure)
    monkeypatch.setattr(evaluator, '_docker', docker)

    assert run.run() is not docker_fails
    codex.run.assert_called_once_with('agent-01.1', ANY, run.task)
    assert (workspace / 'target.py').read_bytes() == (ORIGINAL if docker_fails else CANDIDATE)
    if not docker_fails:
        assert read_json(tmp_path / 'agent-01.1.evaluation.json')['accepted'] is True


def test_comparison_replays_completed_turns_and_retries_a_partial_record(tmp_path, monkeypatch, fake_which):
    manifest = tmp_path / 'compare.toml'
    body = (INPUTS / 'evaluated.toml').read_text()
    body = (
        body.replace('repo = "repo"', f'repo = {json.dumps(str(INPUTS / "repo"))}')
        .replace('build_root = "build"', f'build_root = {json.dumps(str(INPUTS / "build"))}')
        .replace('task_file = "task.txt"', f'task_file = {json.dumps(str(INPUTS / "task.txt"))}')
        .replace('variants = ["depencity"]', 'variants = ["plain", "depencity"]')
    )
    manifest.write_text(body + '\n[agent]\niterations = 1\n')
    log = tmp_path / 'logs' / RUN_ID
    plain = log / 'plain/workspace'
    profiled = log / 'depencity/workspace'
    attempted = []

    def run_codex(codex, iteration, workspace, task):
        assert codex.with_depencity == iteration.startswith('depencity.')
        assert (workspace / 'test_target.py').read_bytes() == (INPUTS / 'repo/test_target.py').read_bytes()
        attempted.append((iteration, (workspace / 'target.py').read_bytes()))
        (workspace / 'target.py').write_bytes(CANDIDATE)
        if iteration == 'plain.1' and attempted.count(('plain.1', ORIGINAL)) == 1:
            return CodexResult(7, '')
        return CodexResult(0, 'done')

    def measure(evaluator_instance):
        return {METRIC: 4 if evaluator_instance.target.read_bytes() == ORIGINAL else 2}

    def docker(path, workspace, build_root, dockerfile, command):
        return json.dumps({'returncode': int(workspace == plain), 'output': 'tests finished'})

    monkeypatch.setattr(runner.Codex, 'run', create_autospec(runner.Codex.run, side_effect=run_codex))
    monkeypatch.setattr(Evaluator, 'measure', measure)
    monkeypatch.setattr(evaluator, '_docker', docker)
    subprocess_run = Mock(return_value=subprocess.CompletedProcess([], 0, 'revision\n'))
    monkeypatch.setattr(subprocess, 'run', subprocess_run)
    cli = CliRunner()
    args = ['run', str(manifest)]

    first = cli.invoke(runner.main, args, catch_exceptions=False)

    assert first.exit_code == 1
    assert read_json(log / 'depencity/depencity.1.evaluation.json')['status'] == 'accepted'
    assert read_json(log / 'plain/plain.1.evaluation.json')['status'] == 'agent_failed'
    (log / 'plain/plain.1.evaluation.json').write_text('{')
    for workspace in (plain, profiled):
        (workspace / 'target.py').write_bytes(b'interrupted edit\n')

    resumed = cli.invoke(runner.main, [*args, '--continue'], catch_exceptions=False)

    assert resumed.exit_code == 0
    assert read_json(log / 'plain/plain.1.evaluation.json')['status'] == 'rejected'
    assert (profiled / 'target.py').read_bytes() == CANDIDATE
    assert (plain / 'target.py').read_bytes() == ORIGINAL
    assert sorted(attempted) == [
        ('depencity.1', ORIGINAL), ('plain.1', ORIGINAL), ('plain.1', ORIGINAL),
    ]

    (plain / 'target.py').write_bytes(b'interrupted after rejection\n')
    resumed = cli.invoke(runner.main, [*args, '--continue'], catch_exceptions=False)

    assert resumed.exit_code == 0
    assert len(attempted) == 3
    assert (plain / 'target.py').read_bytes() == ORIGINAL
    subprocess_run.assert_called_once_with(
        ['git', 'rev-parse', 'HEAD'], cwd=str(INPUTS / 'repo'), capture_output=True, text=True,
    )


def test_comparison_does_not_start_turns_after_interrupt(tmp_path, fake_which, monkeypatch):
    comparison = ComparisonRunner(
        INPUTS / 'repo', tmp_path, 'task', 'model', 1, Path('target.py'), (METRIC,),
        Path('test_target.py'), False, False, INPUTS / 'build', 'Dockerfile.test',
    )
    run_codex = Mock()
    monkeypatch.setattr(runner.Codex, 'run', run_codex)

    comparison.handle_interrupt(None, None)

    assert comparison.run() is True
    run_codex.assert_not_called()
