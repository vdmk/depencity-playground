"""Exercise the extraction gate against tracked changes in a real repository."""

from subprocess import check_output
from unittest.mock import Mock

import pytest

from agent_runner.codex import CodexResult
from agent_runner.runners.fresh import FreshRunner
from agent_runner.git import Branch
from agent_runner.runners.incremental import IncrementalRunner


LOOP = """    for task in tasks:
        if task.ready():
            if not task.execute():
                return False
    return True
"""
BEFORE = "def run(tasks):\n" + LOOP
EXTRACT_LOOP = "def run(tasks):\n    return process(tasks)\n\ndef process(tasks):\n"
UNCHANGED_CALLER = "\ndef main(tasks):\n    return run(tasks)\n"


@pytest.mark.parametrize(('candidate', 'rejected_helper'), [
    pytest.param(
        EXTRACT_LOOP + """    for task in tasks:
        if task.ready() and not task.execute():
            return False
    return True
""", None, id='both-limits-pass'),
    pytest.param(
        EXTRACT_LOOP + LOOP, 'process', id='combined-paths-do-not-decrease'),
    pytest.param(
        BEFORE.replace('task.ready()', 'ready(task)')
        + '\ndef ready(task):\n    return task.ready()\n',
        'ready', id='helper-smaller-than-caller'),
])
def test_extraction_limits_gate_git_commit(tmp_path, candidate, rejected_helper, capsys):
    def git(*args):
        return check_output(['git', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q')
    git('config', 'user.name', 'Test Worker')
    git('config', 'user.email', 'worker@example.test')
    source = tmp_path / 'tasks.py'
    source.write_text(BEFORE + UNCHANGED_CALLER)
    git('add', 'tasks.py')
    git('commit', '-qm', 'Baseline')
    baseline = git('rev-parse', 'HEAD')
    runner = IncrementalRunner(
        Mock(), tmp_path, 1, 'task', 1, 'run', enforce_extraction_path_limits=True,
    )
    source.write_text(candidate + UNCHANGED_CALLER)

    status, reason = runner.commit_candidate('agent-01', 1, Branch(tmp_path), 'Process tasks')

    if rejected_helper:
        assert status == 'rejected'
        assert git('rev-parse', 'HEAD') == baseline
        assert git('diff', '--name-only') == 'tasks.py'
        assert f'rejected extraction: tasks.py: run -> {rejected_helper}:' in capsys.readouterr().out
    else:
        assert status == 'accepted'
        assert git('rev-parse', 'HEAD') != baseline
        assert git('show', 'HEAD:tasks.py') == source.read_text().strip()


@pytest.mark.parametrize('runner_type', [FreshRunner, IncrementalRunner])
def test_next_iteration_starts_clean_after_rejection(runner_type, tmp_path):
    def git(path, *args):
        return check_output(['git', *args], cwd=path, text=True).strip()

    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Test Worker')
    git(tmp_path, 'config', 'user.email', 'worker@example.test')
    (tmp_path / 'tasks.py').write_text(BEFORE)
    git(tmp_path, 'add', 'tasks.py')
    git(tmp_path, 'commit', '-qm', 'Baseline')
    heads = []

    def turn(label, workspace, task):
        source = workspace / 'tasks.py'
        heads.append(git(workspace, 'rev-parse', 'HEAD'))
        if label.endswith('.2'):
            source.write_text(source.read_text().replace('task.ready()', 'ready(task)')
                              + '\ndef ready(task):\n    return task.ready()\n')
            git(workspace, 'add', 'tasks.py')
            (workspace / 'scratch.py').touch()
        else:
            assert git(workspace, 'status', '--porcelain') == ''
            if label.endswith('.3'):
                expected = BEFORE + '# first\n' if runner_type is IncrementalRunner else BEFORE
                assert source.read_text() == expected
                assert 'tasks.py: run -> ready' in task
                return CodexResult(0, 'Review task processing', 'tasks.py run: cleanup order prevents extraction')
            if label.endswith('.4'):
                assert 'cleanup order prevents extraction' in task
                assert 'Choose an untried scope' in task
            source.write_text(source.read_text() + ('# first\n' if label.endswith('.1') else '# last\n'))
        return CodexResult(0, label)

    codex = Mock(log_dir=tmp_path / '.git')
    codex.run.side_effect = turn
    runner = runner_type(codex, tmp_path, 1, 'task', 4, 'run', enforce_extraction_path_limits=True)
    assert runner.run() is True
    assert len(heads) == 4
    assert heads[2] == heads[1]
    iteration = 1 if runner_type is IncrementalRunner else 4
    tip = f'codex-batch/run/agent-01/iteration-{iteration}'
    assert git(tmp_path, 'log', '-1', '--format=%s', tip) == 'auto-refactor: agent-01.4'
