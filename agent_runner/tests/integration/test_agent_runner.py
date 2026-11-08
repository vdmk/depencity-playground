import json
import os
import signal
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_runner import runner as agent_runner
from agent_runner import git as worker_git
from agent_runner import codex as codex_execution


def _write_codex(path, script):
    summary_output = (
        'previous=""\n'
        'for argument in "$@"; do\n'
        '  if [ "$previous" = "--output-last-message" ]; then\n'
        '    printf \'{"short_summary":"simplify calculator parsing"}\\n\' > "$argument"\n'
        '  fi\n'
        '  previous="$argument"\n'
        'done\n'
    )
    path.write_text(script.replace('#!/bin/sh\n', '#!/bin/sh\n' + summary_output, 1))


def _invoke_parallel(arguments):
    return CliRunner().invoke(agent_runner.main, [
        'run-in-parallel', '--log-root', 'agent-runner-files/logs',
        *arguments,
    ])


def _run_git(repo, *args):
    return subprocess.run(
        ['git', '-C', str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _create_repository(path):
    path.mkdir()
    _run_git(path, 'init', '-b', 'main')
    _run_git(path, 'config', 'user.name', 'Test')
    _run_git(path, 'config', 'user.email', 'test@example.com')
    (path / '.gitignore').write_text('.worktrees/\nagent-runner-files/logs/\n')
    (path / 'AGENTS.md').write_text('Project guidance.\n')
    (path / 'module.py').write_text('value = 1\n')
    source_root = path / 'agent_runner/src/agent_runner'
    source_root.mkdir(parents=True)
    (source_root / '__init__.py').write_text('')
    (source_root / 'alpha.py').write_text('alpha = 1\n')
    (source_root / 'beta.py').write_text('beta = 1\n')
    graph_root = path / 'depencity/src/depencity'
    graph_root.mkdir(parents=True)
    (graph_root / '__init__.py').write_text('')
    for name in ('delta', 'epsilon', 'gamma', 'zeta'):
        (graph_root / f'{name}.py').write_text(f'{name} = 1\n')
    _run_git(path, 'add', '.')
    _run_git(path, 'commit', '-m', 'initial')


def test_runner_relaunches_codex_with_indexed_logs(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    monkeypatch.setenv('CODEX_CAPTURE_DIR', str(capture_dir))
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        'name="$(basename "$(dirname "$PWD")")"\n'
        'iteration="$(basename "$PWD")"\n'
        'printf "%s\\n" "$@" > "$CODEX_CAPTURE_DIR/$name.$iteration.args"\n'
        'marker="$CODEX_CAPTURE_DIR/$name.once"\n'
        'if [ -f "$marker" ]; then exit 1; fi\n'
        'touch "$marker"\n'
        'printf "candidate = 1\\n" > candidate.py\n'
        'git add candidate.py\n'
        'git commit -m "refactor: candidate" >/dev/null\n'
        'printf \'{"type":"turn.completed"}\\n\'\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '3',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    output = result.output
    for name in ('agent-01', 'agent-02', 'agent-03'):
        assert f'{name}.1: launching' in output
        assert f'Created worktree: {repo}/.worktrees/codex-batch/' in output
        assert f'{name}.1: finished with return code 0' in output
        assert f'{name}.2: launching' in output
        assert f'{name}.2: finished with return code 1' in output
        worker_root = next((repo / '.worktrees' / 'codex-batch').rglob(f'{name}'))
        first_worktree = worker_root / 'iteration-1'
        worker_worktree = worker_root / 'iteration-2'
        assert not first_worktree.exists()
        assert not worker_worktree.exists()
        logs = sorted((repo / 'agent-runner-files' / 'logs').rglob(f'{name}.*.jsonl'))
        assert len(logs) == 2
        assert 'turn.completed' in logs[0].read_text()
        arguments = (capture_dir / f'{name}.iteration-1.args').read_text().splitlines()
        next_arguments = (capture_dir / f'{name}.iteration-2.args').read_text().splitlines()
        assert '--ephemeral' in arguments
        assert '--ignore-user-config' not in arguments
        assert arguments[arguments.index('--sandbox') + 1] == 'workspace-write'
        assert 'approval_policy="on-request"' in arguments
        assert not any(value.startswith('mcp_servers.') for value in arguments)
        assert arguments[arguments.index('--model') + 1] == 'gpt-6-luna'
        task = arguments[-1]
        assert task.startswith('Make one coherent, behavior-preserving refactoring.')
        assert task.startswith(agent_runner.DEFAULT_TASK)
        assert "Do not commit changes" in task
        assert next_arguments[-1] == task
        branches = _run_git(repo, 'branch', '--list', f'codex-batch/*/{name}/iteration-*')
        branch_names = [
            line.strip().removeprefix('+ ').removeprefix('* ')
            for line in branches.splitlines()
        ]
        candidate_branch = next(branch for branch in branch_names if branch.endswith('/iteration-1'))
        assert any(branch.endswith('/iteration-2') for branch in branch_names)
        assert _run_git(repo, 'show', f'{candidate_branch}:candidate.py') == 'candidate = 1'
        assert _run_git(repo, 'show', f'{candidate_branch}:candidate.py') == 'candidate = 1'

    assert _run_git(repo, 'branch', '--show-current') == 'main'
    assert _run_git(repo, 'log', '-1', '--format=%s', 'main') == 'initial'


@pytest.mark.parametrize('option, value', [
    ('--workers', '0'),
    ('--workers', '101'),
    ('--iterations', '0'),
    ('--iterations', '1001'),
])
def test_parallel_rejects_invalid_worker_and_iteration_limits(option, value):
    result = _invoke_parallel([option, value])

    assert result.exit_code == 2
    assert 'Invalid value for' in result.output


def test_runner_passes_same_task_to_all_workers(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    tasks = {}

    def run_agent(_self, log_name, _worktree, task):
        name = log_name.rsplit('.', 1)[0]
        tasks[name] = task
        return codex_execution.CodexResult(1, '')

    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: '/codex')
    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)

    result = _invoke_parallel(['--repo', str(repo), '--workers', '7'])

    assert result.exit_code == 1
    assert len(tasks) == 7
    assert len(set(tasks.values())) == 1
    assert all(task.startswith(agent_runner.DEFAULT_TASK) for task in tasks.values())


def test_runner_uses_checked_out_commit_as_worktree_base(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    _run_git(repo, 'switch', '-c', 'review')
    (repo / 'review_only.py').write_text('review = True\n')
    _run_git(repo, 'add', 'review_only.py')
    _run_git(repo, 'commit', '-m', 'review base')
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    monkeypatch.setenv('CODEX_CAPTURE_DIR', str(capture_dir))
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        '[ -f review_only.py ] && touch "$CODEX_CAPTURE_DIR/review-base-seen"\n'
        'exit 1\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '1',
    ])

    assert result.exit_code == 1, result.output
    assert (capture_dir / 'review-base-seen').exists()
    assert _run_git(repo, 'branch', '--show-current') == 'review'


def test_runner_uses_latest_starting_branch_tip_for_later_iterations(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    worktrees = []
    starts = []

    def run_agent(_self, log_name, worktree, *_args):
        run_index = int(log_name.rsplit('.', 1)[1])
        worktrees.append(worktree)
        starts.append(_run_git(worktree, 'rev-parse', 'HEAD'))
        if run_index == 2:
            assert (worktree / 'accepted.py').exists()
        if run_index == 1:
            (worktree / 'accepted.py').write_text('accepted = True\n')
            _run_git(worktree, 'add', 'accepted.py')
            _run_git(worktree, 'commit', '-m', 'refactor: accepted change')
            commit = _run_git(worktree, 'rev-parse', 'HEAD')
            _run_git(repo, 'cherry-pick', commit)
            return codex_execution.CodexResult(0, 'simplify calculator parsing')
        return codex_execution.CodexResult(1, '')

    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: '/codex')
    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '1',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    assert len(worktrees) == 2
    assert all(not path.exists() for path in worktrees)
    assert starts[1] == _run_git(repo, 'rev-parse', 'HEAD')


def test_runner_retires_failed_agents_and_relaunches_remaining_agents(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    monkeypatch.setenv('CODEX_CAPTURE_DIR', str(capture_dir))
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        'name="$(basename "$(dirname "$PWD")")"\n'
        'touch "$CODEX_CAPTURE_DIR/$name.started"\n'
        'case "$name" in\n'
        '  agent-01) exit 1;;\n'
        '  *) marker="$CODEX_CAPTURE_DIR/$name.once"; '
        '[ -f "$marker" ] && exit 1; touch "$marker";;\n'
        'esac\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '2',
        '--iterations', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01.1: finished with return code 1' in result.output
    assert 'agent-01: stopped after nonzero exit' in result.output
    assert 'agent-02.1: finished with return code 0' in result.output
    assert 'agent-02.2: finished with return code 1' in result.output
    assert 'No agents remain; stopping.' in result.output
    assert result.output.count('agent-01.1: finished with return code 1') == 1
    assert sorted(path.name for path in capture_dir.iterdir()) == [
        'agent-01.started',
        'agent-02.once',
        'agent-02.started',
    ]


def test_agents_relaunch_independently(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    monkeypatch.setenv('CODEX_CAPTURE_DIR', str(capture_dir))
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        'name="$(basename "$(dirname "$PWD")")"\n'
        'if [ "$name" = agent-01 ]; then\n'
        '  marker="$CODEX_CAPTURE_DIR/agent-01.once"\n'
        '  if [ -f "$marker" ]; then exit 1; fi\n'
        '  touch "$marker"\n'
        '  count=0\n'
        '  while [ ! -f "$CODEX_CAPTURE_DIR/agent-02.run2" ] && [ "$count" -lt 60 ]; do\n'
        '    sleep 0.05\n'
        '    count=$((count + 1))\n'
        '  done\n'
        '  [ -f "$CODEX_CAPTURE_DIR/agent-02.run2" ] && touch "$CODEX_CAPTURE_DIR/agent-02-ran-first"\n'
        'else\n'
        '  marker="$CODEX_CAPTURE_DIR/agent-02.once"\n'
        '  if [ -f "$marker" ]; then touch "$CODEX_CAPTURE_DIR/agent-02.run2"; exit 1; fi\n'
        '  touch "$marker"\n'
        'fi\n'
        'printf "candidate = 1\\n" > candidate.py\n'
        'git add candidate.py\n'
        'git commit -m "refactor: candidate" >/dev/null\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '2',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    assert (capture_dir / 'agent-02-ran-first').exists()
    assert result.output.index('agent-02.2: launching') < result.output.index(
        'agent-01.1: finished with return code 0'
    )


def test_runner_stops_relaunching_after_first_interrupt(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: 'codex')
    calls = []

    def interrupt_agent(_self, log_name, *_args):
        calls.append(log_name.rsplit('.', 1)[0])
        os.kill(os.getpid(), signal.SIGINT)
        return codex_execution.CodexResult(0, 'simplify calculator parsing')

    monkeypatch.setattr(agent_runner.Codex, 'run', interrupt_agent)

    assert agent_runner.SequentialRunner(
        agent_runner.Codex('model', tmp_path), repo, 'task', 1,
    ).run()
    assert calls == ['agent-01']


def test_runner_retires_agents_that_cannot_start(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    missing_codex = tmp_path / 'missing-codex'
    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: str(missing_codex))

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01: stopped after runner error (' in result.output
    assert 'agent-02: stopped after runner error (' in result.output
    assert 'No such file or directory' in result.output
    assert len(list((repo / 'agent-runner-files' / 'logs').rglob('*.jsonl'))) == 2


def test_runner_continues_when_one_agent_cannot_create_worktree(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: 'codex')
    create_worktree = worker_git.create_worktree
    started_agents = []

    def create_agent_worktree(repo, root, name, iteration, base):
        if name == 'agent-01':
            raise OSError('worktree unavailable')
        return create_worktree(repo, root, name, iteration, base)

    def run_agent(_self, log_name, *_args):
        started_agents.append(log_name.rsplit('.', 1)[0])
        return codex_execution.CodexResult(1, '')

    monkeypatch.setattr(worker_git, 'create_worktree', create_agent_worktree)
    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)

    result = _invoke_parallel([
        '--repo', str(repo),
        '--workers', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01: stopped after runner error (worktree unavailable)' in result.output
    assert started_agents == ['agent-02']


def test_runner_requires_a_clean_repository(tmp_path):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    (repo / 'uncommitted.py').write_text('changed = True\n')

    result = _invoke_parallel(['--repo', str(repo)])

    assert result.exit_code == 1
    assert 'repository must be clean' in result.output


def test_sequential_turns_build_commit_chain_in_target_repository(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    # Generic repositories do not need AGENTS.md or the runner's source layout.
    _run_git(repo, 'rm', '-r', 'AGENTS.md', 'agent_runner', 'depencity')
    _run_git(repo, 'commit', '-m', 'generic project')
    original = _run_git(repo, 'rev-parse', 'HEAD')
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        'printf "change = True\\n" >> module.py\n'
        'git add module.py\n'
        'git commit -m "refactor: next turn" >/dev/null\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = CliRunner().invoke(agent_runner.main, [
        'run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(repo), '--iterations', '3', '--task', 'Refactor module.py.',
    ])

    assert result.exit_code == 0, result.output
    assert not (repo / '.worktrees').exists()
    assert _run_git(repo, 'rev-list', '--count', f'{original}..HEAD') == '3'
    assert (repo / 'module.py').read_text().count('change = True') == 3
    assert _run_git(repo, 'branch', '--show-current') == 'main'
    assert len(list((repo / 'agent-runner-files/logs').rglob('*.jsonl'))) == 3


@pytest.mark.parametrize('failure', ['dirty', 'nonzero'])
def test_sequential_stops_and_preserves_failed_turn(tmp_path, monkeypatch, failure):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    calls = []

    def run_agent(_self, log_name, worktree, *_args):
        calls.append(int(log_name.rsplit('.', 1)[1]))
        (worktree / 'module.py').write_text('incomplete = True\n')
        return codex_execution.CodexResult(1 if failure == 'nonzero' else 0, 'simplify parsing')

    monkeypatch.setattr(codex_execution.shutil, 'which', lambda _name: 'codex')
    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = CliRunner().invoke(agent_runner.main, [
        'run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(repo), '--iterations', '3',
    ])

    assert result.exit_code == (1 if failure == 'nonzero' else 0), result.output
    assert calls == ([1] if failure == 'nonzero' else [1, 2, 3])
    assert not (repo / '.worktrees').exists()
    assert (repo / 'module.py').read_text() == 'incomplete = True\n'


def test_parallel_single_worker_uses_independent_branches(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    workspaces = []

    def run_agent(_self, log_name, workspace, *_args):
        workspaces.append(workspace)
        return codex_execution.CodexResult(0, 'simplify calculator parsing')

    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = CliRunner().invoke(agent_runner.main, [
        'run-in-parallel', '--log-root', 'agent-runner-files/logs', '--repo', str(repo), '--workers', '1', '--iterations', '2',
    ])
    assert result.exit_code == 0, result.output
    assert len(set(workspaces)) == 2
    assert all(path != repo and not path.exists() for path in workspaces)


def test_single_worker_without_git_works_outside_git(tmp_path, monkeypatch):
    workspaces = []

    def run_agent(_self, log_name, workspace, task):
        workspaces.append(workspace)
        assert task.startswith('Do the task Do not commit changes')
        return codex_execution.CodexResult(0, 'simplify calculator parsing')

    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = CliRunner().invoke(agent_runner.main, [
        'run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(tmp_path), '--task', 'Do the task',
    ])
    assert result.exit_code == 0, result.output
    assert workspaces == [tmp_path]
    assert not (tmp_path / '.worktrees').exists()


@pytest.mark.parametrize('dirty', [False, True])
def test_worktree_context_cleanup_on_exception_preserves_branch_and_edits(tmp_path, dirty):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    worktrees = worker_git.Git(repo, 'context-test')
    with pytest.raises(RuntimeError, match='turn failed'):
        with worktrees.create_workspace_branch('agent-01', 1) as branch_workspace:
            workspace = branch_workspace.work_dir
            branch = _run_git(workspace, 'branch', '--show-current')
            if dirty:
                (workspace / 'module.py').write_text('unfinished = True\n')
                (workspace / 'new.py').write_text('untracked = True\n')
            raise RuntimeError('turn failed')
    assert _run_git(repo, 'rev-parse', '--verify', branch)
    assert workspace.exists() == dirty
    if dirty:
        assert (workspace / 'module.py').read_text() == 'unfinished = True\n'
        assert (workspace / 'new.py').exists()
    assert str(workspace) in _run_git(repo, 'worktree', 'list') if dirty else str(workspace) not in _run_git(repo, 'worktree', 'list')


@pytest.mark.parametrize('relative', [False, True])
def test_runner_uses_configured_log_root(tmp_path, monkeypatch, relative):
    repo = tmp_path / 'project'
    repo.mkdir()
    log_root = repo / 'custom-logs' if relative else tmp_path / 'external-logs'
    captured = []

    def run_agent(self, iteration_name, _workspace, _task):
        captured.append((self.log_dir, iteration_name))
        return codex_execution.CodexResult(0, 'simplify calculator parsing')

    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = CliRunner().invoke(agent_runner.main, [
        'run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(repo),
        '--log-root', 'custom-logs' if relative else str(log_root),
    ])
    assert result.exit_code == 0, result.output
    log_dir, iteration_name = captured[0]
    assert log_dir.parent == log_root
    assert log_dir.is_dir()
    assert iteration_name == 'agent-01.1'
    assert not (repo / 'agent-runner-files').exists()


@pytest.mark.parametrize('use_git', [False, True])
def test_runner_commits_with_summary_only_when_worktrees_enabled(tmp_path, monkeypatch, use_git):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    base = _run_git(repo, 'rev-parse', 'HEAD')
    codex = tmp_path / 'codex'
    _write_codex(codex,
        '#!/bin/sh\n'
        'previous=""\n'
        'for argument in "$@"; do\n'
        '  if [ "$previous" = "--output-last-message" ]; then\n'
        '    printf \'{"short_summary":"simplify module initialization"}\\n\' > "$argument"\n'
        '  fi\n'
        '  previous="$argument"\n'
        'done\n'
        'printf "value = 2\\n" > module.py\n'
        'printf "new_value = 3\\n" > new.py\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')
    arguments = ['run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(repo)]
    if use_git:
        arguments[0] = 'run-in-parallel'
        arguments.extend(['--workers', '1', '--iterations', '2'])
    result = CliRunner().invoke(agent_runner.main, arguments)
    assert result.exit_code == 0, result.output
    assert _run_git(repo, 'rev-parse', 'HEAD') == base
    summaries = list((repo / 'agent-runner-files/logs').rglob('*.summary.json'))
    assert len(summaries) == (2 if use_git else 1)
    assert all(json.loads(path.read_text()) == {'short_summary': 'simplify module initialization'}
               for path in summaries)
    if use_git:
        branches = _run_git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/codex-batch').splitlines()
        assert len(branches) == 2
        for branch in branches:
            assert _run_git(repo, 'rev-list', '--count', f'{base}..{branch}') == '1'
            assert _run_git(repo, 'log', '-1', '--format=%s', branch) == 'auto-refactor: simplify module initialization'
            assert _run_git(repo, 'show', f'{branch}:module.py') == 'value = 2'
            assert _run_git(repo, 'show', f'{branch}:new.py') == 'new_value = 3'
        assert not list((repo / '.worktrees').rglob('iteration-*'))
        assert not _run_git(repo, 'status', '--porcelain')
    else:
        assert (repo / 'module.py').read_text() == 'value = 2\n'
        assert (repo / 'new.py').exists()
        assert _run_git(repo, 'status', '--porcelain')


@pytest.mark.parametrize('return_code', [0, 1])
def test_runner_preserves_uncommitted_work_on_missing_summary_or_failure(tmp_path, monkeypatch, return_code):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    base = _run_git(repo, 'rev-parse', 'HEAD')
    codex = tmp_path / 'codex'
    codex.write_text(
        '#!/bin/sh\n'
        'printf "unfinished = True\\n" > module.py\n'
        f'exit {return_code}\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')
    result = CliRunner().invoke(agent_runner.main, [
        'run-in-parallel', '--log-root', 'agent-runner-files/logs', '--repo', str(repo), '--workers', '1', '--iterations', '2',
    ])
    assert result.exit_code == 1, result.output
    workspace, = (repo / '.worktrees').rglob('iteration-*')
    assert (workspace / 'module.py').read_text() == 'unfinished = True\n'
    assert _run_git(workspace, 'rev-parse', 'HEAD') == base
    if return_code == 1:
        assert 'stopped after nonzero exit' in result.output


def test_sequential_rejects_concurrent_workers(tmp_path, monkeypatch):
    def unexpected_run(*args):
        pytest.fail('workers must not start without Git isolation')

    monkeypatch.setattr(agent_runner.Codex, 'run', unexpected_run)
    result = CliRunner().invoke(agent_runner.main, [
        'run-sequential', '--log-root', 'agent-runner-files/logs', '--repo', str(tmp_path), '--workers', '2',
    ])
    assert result.exit_code == 2
    assert 'No such option' in result.output
    assert '--workers' in result.output
    assert not (tmp_path / 'agent-runner-files').exists()


@pytest.mark.parametrize('command', ['run-sequential', 'run-in-parallel'])
def test_log_root_is_required(command, tmp_path):
    result = CliRunner().invoke(agent_runner.main, [command, '--repo', str(tmp_path)])
    assert result.exit_code == 2
    assert 'Missing option' in result.output
    assert '--log-root' in result.output
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('branch_mode', ['fresh', 'incremental'])
def test_branch_modes_control_workspace_reuse_and_commit_ancestry(tmp_path, monkeypatch, branch_mode):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    base = _run_git(repo, 'rev-parse', 'HEAD')
    workspaces = {}

    def run_agent(_self, iteration_name, work_dir, _task):
        name, iteration = iteration_name.rsplit('.', 1)
        iteration = int(iteration)
        workspaces[iteration_name] = work_dir
        module = work_dir / 'module.py'
        before = module.read_text()
        expected_prior = iteration - 1 if branch_mode == 'incremental' else 0
        assert before.count('candidate = True') == expected_prior
        module.write_text(before + 'candidate = True\n')
        return codex_execution.CodexResult(0, f'improve {name} iteration {iteration}')

    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = _invoke_parallel([
        '--repo', str(repo), '--workers', '2', '--iterations', '3', '--branch-mode', branch_mode,
    ])
    assert result.exit_code == 0, result.output
    branches = _run_git(repo, 'for-each-ref', '--format=%(refname)', 'refs/heads/codex-batch').splitlines()
    expected_branches, expected_commits = (6, 1) if branch_mode == 'fresh' else (2, 3)
    assert len(branches) == expected_branches
    assert len(set(workspaces.values())) == expected_branches
    for branch in branches:
        assert _run_git(repo, 'rev-list', '--count', f'{base}..{branch}') == str(expected_commits)
        assert _run_git(repo, 'show', f'{branch}:module.py').count('candidate = True') == expected_commits
    assert all(not path.exists() for path in workspaces.values())
    assert _run_git(repo, 'rev-parse', 'HEAD') == base
    assert not _run_git(repo, 'status', '--porcelain')


@pytest.mark.parametrize('failure', ['nonzero', 'exception'])
def test_incremental_failure_keeps_prior_commit_and_uncommitted_edits(tmp_path, monkeypatch, failure):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    base = _run_git(repo, 'rev-parse', 'HEAD')
    calls = []

    def run_agent(_self, iteration_name, work_dir, _task):
        calls.append((iteration_name, work_dir))
        module = work_dir / 'module.py'
        if iteration_name.endswith('.1'):
            module.write_text('accepted = True\n')
            return codex_execution.CodexResult(0, 'simplify module initialization')
        assert module.read_text() == 'accepted = True\n'
        module.write_text('unfinished = True\n')
        if failure == 'exception':
            raise OSError('agent unavailable')
        return codex_execution.CodexResult(1, '')

    monkeypatch.setattr(agent_runner.Codex, 'run', run_agent)
    result = _invoke_parallel([
        '--repo', str(repo), '--workers', '1', '--iterations', '3', '--branch-mode', 'incremental',
    ])
    assert result.exit_code == 1, result.output
    assert len(calls) == 2
    workspace = calls[0][1]
    assert calls[1][1] == workspace
    assert (workspace / 'module.py').read_text() == 'unfinished = True\n'
    assert _run_git(workspace, 'show', 'HEAD:module.py') == 'accepted = True'
    assert _run_git(workspace, 'rev-list', '--count', f'{base}..HEAD') == '1'
    assert _run_git(repo, 'rev-parse', 'HEAD') == base
