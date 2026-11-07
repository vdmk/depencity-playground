import json
import os
import signal
import subprocess

import pytest
from click.testing import CliRunner

from agent_runner import runner as agent_runner


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
    codex.write_text(
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

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '3',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    output = result.output
    assignments = {
        'agent-01': (
            'agent_runner/src/agent_runner/alpha.py',
            'depencity/src/depencity/epsilon.py',
        ),
        'agent-02': (
            'agent_runner/src/agent_runner/beta.py',
            'depencity/src/depencity/gamma.py',
        ),
        'agent-03': (
            'depencity/src/depencity/delta.py',
            'depencity/src/depencity/zeta.py',
        ),
    }
    for name, files in assignments.items():
        assert f'Launching {name} run 1: branch=codex-batch/' in output
        assert f'worktree={repo}/.worktrees/codex-batch/' in output
        assert f'{name} run 1: finished with return code 0' in output
        assert f'Launching {name} run 2: branch=codex-batch/' in output
        assert f'{name}: committed ' in output
        assert 'next iteration gets a fresh worktree' in output
        assert f'{name} run 2: finished with return code 1' in output
        worker_root = next((repo / '.worktrees' / 'codex-batch').rglob(f'{name}'))
        first_worktree = worker_root / 'iteration-1'
        worker_worktree = worker_root / 'iteration-2'
        assert (first_worktree / 'AGENTS.md').exists()
        assert (worker_worktree / 'AGENTS.md').exists()
        assert _run_git(worker_worktree, 'branch', '--show-current').endswith(f'{name}/iteration-2')
        assert not (worker_worktree / 'candidate.py').exists()
        logs = sorted((repo / 'agent-runner-files' / 'logs').rglob(f'{name}.*.jsonl'))
        assert len(logs) == 2
        assert 'turn.completed' in logs[0].read_text()
        arguments = (capture_dir / f'{name}.iteration-1.args').read_text().splitlines()
        next_arguments = (capture_dir / f'{name}.iteration-2.args').read_text().splitlines()
        assert '--ephemeral' in arguments
        assert '--ignore-user-config' in arguments
        assert arguments[arguments.index('--sandbox') + 1] == 'workspace-write'
        assert 'approval_policy="on-request"' in arguments
        assert 'mcp_servers.depencity.default_tools_approval_mode="approve"' in arguments
        assert 'mcp_servers.agent-runner.default_tools_approval_mode="approve"' in arguments
        assert (
            'mcp_servers.agent-runner.enabled_tools='
            '["docker_test", "git_commit", "reviewed_commits"]'
        ) in arguments
        assert arguments[arguments.index('--model') + 1] == 'gpt-6-luna'
        task = arguments[-1]
        assert task.startswith('Inspect the compact profile for the whole module or package')
        assert task.endswith(f'Refactor only these source files, in order: {", ".join(files)}. ')
        assert next_arguments[-1].endswith(
            f'Refactor only these source files, in order: {", ".join(reversed(files))}. '
        )
        graph_mcp_args = json.loads(
            next(value for value in arguments if value.startswith('mcp_servers.depencity.args='))
            .partition('=')[2]
        )
        runner_mcp_args = json.loads(
            next(value for value in arguments if value.startswith('mcp_servers.agent-runner.args='))
            .partition('=')[2]
        )
        worktree = arguments[arguments.index('--cd') + 1]
        assert graph_mcp_args[:4] == ['run', '--project', str(repo), 'depencity-mcp']
        assert graph_mcp_args[graph_mcp_args.index('--workspace') + 1] == worktree
        assert runner_mcp_args[:3] == ['run', '--project', str(repo)]
        assert runner_mcp_args[runner_mcp_args.index('--build-root') + 1] == str(repo)
        assert runner_mcp_args[runner_mcp_args.index('--dockerfile') + 1] == 'docker/test/Dockerfile'
        assert f'mcp_servers.depencity.cwd={json.dumps(worktree)}' in arguments
        assert f'mcp_servers.agent-runner.cwd={json.dumps(worktree)}' in arguments

        branches = _run_git(repo, 'branch', '--list', f'codex-batch/*/{name}/iteration-*')
        branch_names = [
            line.strip().removeprefix('+ ').removeprefix('* ')
            for line in branches.splitlines()
        ]
        candidate_branch = next(branch for branch in branch_names if branch.endswith('/iteration-1'))
        assert any(branch.endswith('/iteration-2') for branch in branch_names)
        assert _run_git(repo, 'show', f'{candidate_branch}:candidate.py') == 'candidate = 1'
        assert (first_worktree / 'candidate.py').exists()

    assert _run_git(repo, 'branch', '--show-current') == 'main'
    assert _run_git(repo, 'log', '-1', '--format=%s', 'main') == 'initial'


@pytest.mark.parametrize('option, value', [
    ('--count', '0'),
    ('--count', '101'),
    ('--iterations', '0'),
    ('--iterations', '101'),
])
def test_runner_rejects_limits_outside_one_to_one_hundred(option, value):
    result = CliRunner().invoke(agent_runner.main, [option, value])

    assert result.exit_code == 2
    assert 'Invalid value for' in result.output


def test_runner_repeats_files_when_agents_outnumber_them(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    tasks = {}

    def run_agent(name, _index, _worktree, _repo, _logs, _codex, task, _model, _branch):
        tasks[name] = task
        return 1

    monkeypatch.setattr(agent_runner.shutil, 'which', lambda _name: '/codex')
    monkeypatch.setattr(agent_runner, '_run_agent', run_agent)

    result = CliRunner().invoke(agent_runner.main, ['--repo', str(repo), '--count', '7'])

    assert result.exit_code == 1
    assert len(tasks) == 7
    assert tasks['agent-07'] == tasks['agent-01']


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
    codex.write_text(
        '#!/bin/sh\n'
        '[ -f review_only.py ] && touch "$CODEX_CAPTURE_DIR/review-base-seen"\n'
        'exit 1\n'
    )
    codex.chmod(0o755)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '1',
    ])

    assert result.exit_code == 1, result.output
    assert (capture_dir / 'review-base-seen').exists()
    assert _run_git(repo, 'branch', '--show-current') == 'review'


def test_runner_uses_latest_starting_branch_tip_for_later_iterations(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    worktrees = []

    def run_agent(_name, run_index, worktree, *_args):
        worktrees.append(worktree)
        if run_index == 1:
            (worktree / 'accepted.py').write_text('accepted = True\n')
            _run_git(worktree, 'add', 'accepted.py')
            _run_git(worktree, 'commit', '-m', 'refactor: accepted change')
            commit = _run_git(worktree, 'rev-parse', 'HEAD')
            _run_git(repo, 'cherry-pick', commit)
            return 0
        return 1

    monkeypatch.setattr(agent_runner.shutil, 'which', lambda _name: '/codex')
    monkeypatch.setattr(agent_runner, '_run_agent', run_agent)

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '1',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    assert len(worktrees) == 2
    assert (worktrees[0] / 'accepted.py').exists()
    assert (worktrees[1] / 'accepted.py').exists()
    assert _run_git(worktrees[1], 'rev-parse', 'HEAD') == _run_git(repo, 'rev-parse', 'HEAD')


def test_runner_retires_failed_agents_and_relaunches_remaining_agents(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    monkeypatch.setenv('CODEX_CAPTURE_DIR', str(capture_dir))
    codex = tmp_path / 'codex'
    codex.write_text(
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

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '2',
        '--iterations', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01 run 1: finished with return code 1' in result.output
    assert 'agent-01: stopped after nonzero exit' in result.output
    assert 'agent-02 run 1: finished with return code 0' in result.output
    assert 'agent-02 run 2: finished with return code 1' in result.output
    assert 'No agents remain; stopping.' in result.output
    assert result.output.count('agent-01 run 1: finished with return code 1') == 1
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
    codex.write_text(
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

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '2',
        '--iterations', '2',
    ])

    assert result.exit_code == 1, result.output
    assert (capture_dir / 'agent-02-ran-first').exists()
    assert result.output.index('Launching agent-02 run 2') < result.output.index(
        'agent-01 run 1: finished with return code 0'
    )


def test_runner_stops_relaunching_after_first_interrupt(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    monkeypatch.setattr(agent_runner.shutil, 'which', lambda _name: 'codex')
    calls = []

    def interrupt_agent(name, *_args):
        calls.append(name)
        os.kill(os.getpid(), signal.SIGINT)
        return 0

    monkeypatch.setattr(agent_runner, '_run_agent', interrupt_agent)

    assert agent_runner.run(repo, 1, 'task', 'model')
    assert calls == ['agent-01']


def test_runner_retires_agents_that_cannot_start(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    missing_codex = tmp_path / 'missing-codex'
    monkeypatch.setattr(agent_runner.shutil, 'which', lambda _name: str(missing_codex))

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01: stopped after runner error (' in result.output
    assert 'agent-02: stopped after runner error (' in result.output
    assert 'No such file or directory' in result.output
    assert len(list((repo / 'agent-runner-files' / 'logs').rglob('*.jsonl'))) == 2


def test_runner_continues_when_one_agent_cannot_create_worktree(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    monkeypatch.setattr(agent_runner.shutil, 'which', lambda _name: 'codex')
    create_worktree = agent_runner._create_worktree
    started_agents = []

    def create_agent_worktree(repo, root, name, iteration, base):
        if name == 'agent-01':
            raise OSError('worktree unavailable')
        return create_worktree(repo, root, name, iteration, base)

    def run_agent(name, *_args):
        started_agents.append(name)
        return 1

    monkeypatch.setattr(agent_runner, '_create_worktree', create_agent_worktree)
    monkeypatch.setattr(agent_runner, '_run_agent', run_agent)

    result = CliRunner().invoke(agent_runner.main, [
        '--repo', str(repo),
        '--count', '2',
    ])

    assert result.exit_code == 1
    assert 'agent-01: stopped after runner error (worktree unavailable)' in result.output
    assert started_agents == ['agent-02']


def test_runner_requires_a_clean_repository(tmp_path):
    repo = tmp_path / 'repo'
    _create_repository(repo)
    (repo / 'uncommitted.py').write_text('changed = True\n')

    result = CliRunner().invoke(agent_runner.main, ['--repo', str(repo)])

    assert result.exit_code == 1
    assert 'repository must be clean' in result.output
