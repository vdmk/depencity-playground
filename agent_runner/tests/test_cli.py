import json
import os
import subprocess
from pathlib import Path
from unittest.mock import ANY, Mock, call, create_autospec

import pytest
from click.testing import CliRunner

from agent_runner import runner
from agent_runner.codex import CodexResult
from agent_runner.manifest import load_manifest

from .utils import DOCKER, FIXTURES, PROJECT, read_json


pytestmark = pytest.mark.usefixtures('fake_which', 'fixed_runner_metadata')



INPUTS = FIXTURES / 'runner/input'
RUN_ID = '20260102T030405000000Z-42'
HEAD = '0123456789abcdef0123456789abcdef01234567'
TASK = (
    'Simplify the calculation. Do not commit changes. '
    'For short_summary: One concise imperative commit subject, without prefix or commentary. If no changes, write what was attempted. '
    'Put measurements, tradeoffs and validation results in report. '
    'The agent caller will commit as "auto-refactor: {short_summary}".'
)


@pytest.mark.parametrize('mode', ('fresh', 'incremental'))
def test_worktrees(mode, monkeypatch, fake_which, tmp_path, mock_path_writes):
    case = FIXTURES / 'runner' / f'{mode}_worktree'
    manifest = INPUTS / f'{mode}.toml'
    repo = str(manifest.parent)
    log_dir = manifest.parent / 'logs' / RUN_ID
    mkdir, write_text, replace = mock_path_writes
    ledger = tmp_path / 'attempts.jsonl'
    original_open = Path.open

    def open_path(path, *args, **kwargs):
        return original_open(ledger if path == log_dir / 'attempts.jsonl' else path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', open_path)
    branch = f'codex-batch/{RUN_ID}/agent-01'
    first = f'{repo}/.worktrees/{branch}/iteration-1'
    second = f'{repo}/.worktrees/{branch}/iteration-2' if mode == 'fresh' else first
    git_replies = ['', HEAD + '\n', 'refs/heads/main', '', ' M target.py\n', '', '']
    if mode == 'fresh':
        git_replies.extend(['', '', HEAD + '\n', ''])
    git_replies.extend(['', '', ''])
    subprocess_check_output = Mock(side_effect=git_replies)

    subprocess_run = Mock(return_value=subprocess.CompletedProcess([], 0, HEAD + '\n'))
    codex_run = Mock(return_value=CodexResult(0, 'Simplify the calculation'))
    monkeypatch.setattr(runner.Codex, 'run', codex_run)
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=AssertionError('unexpected subprocess')))
    monkeypatch.setattr(subprocess, 'check_output', subprocess_check_output)
    monkeypatch.setattr(subprocess, 'run', subprocess_run)

    result = CliRunner().invoke(
        runner.main, ['run', str(manifest)], prog_name='agent-runner', catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stderr == ''
    assert result.stdout.replace(repo, '<fixture>') == (case / 'expected_output.stdout.txt').read_text()
    assert mkdir.call_args_list == [
        call(log_dir, parents=True),
        call(log_dir, parents=True, exist_ok=True),
    ]
    write_text.assert_called_once_with(
        log_dir / 'metadata.json.tmp', (case / 'expected_output.metadata.json').read_text(),
    )
    replace.assert_called_once_with(log_dir / 'metadata.json.tmp', log_dir / 'metadata.json')

    git_options = {'text': True, 'stderr': subprocess.PIPE}
    git_calls = [
        call(['git', '-C', repo, 'status', '--porcelain'], **git_options),
        call(['git', '-C', repo, 'rev-parse', 'HEAD'], **git_options),
        call(['git', '-C', repo, 'rev-parse', '--symbolic-full-name', 'HEAD'], **git_options),
        call(['git', '-C', repo, 'worktree', 'add', '-b', f'{branch}/iteration-1', first, HEAD], **git_options),
        call(['git', '-C', first, 'status', '--porcelain'], **git_options),
        call(['git', '-C', first, 'add', '--all'], **git_options),
        call(['git', '-C', first, 'commit', '-m', 'auto-refactor: Simplify the calculation'], **git_options),
    ]
    if mode == 'fresh':
        git_calls.extend([
            call(['git', '-C', first, 'status', '--porcelain'], **git_options),
            call(['git', '-C', repo, 'worktree', 'remove', first], **git_options),
            call(['git', '-C', repo, 'rev-parse', 'refs/heads/main'], **git_options),
            call(['git', '-C', repo, 'worktree', 'add', '-b', f'{branch}/iteration-2', second, HEAD], **git_options),
        ])
    git_calls.extend([
        call(['git', '-C', second, 'status', '--porcelain'], **git_options),
        call(['git', '-C', second, 'status', '--porcelain'], **git_options),
        call(['git', '-C', repo, 'worktree', 'remove', second], **git_options),
    ])
    assert subprocess_check_output.call_args_list == git_calls
    subprocess_run.assert_called_once_with(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True,
    )
    assert [json.loads(line)['status'] for line in ledger.read_text().splitlines()] == ['accepted', 'no_change']
    assert codex_run.call_args_list == [
        call('agent-01.1', Path(first), TASK + ' Refactor only these source files, in order: repo/target.py.'),
        call('agent-01.2', Path(second), TASK + ' Refactor only these source files, in order: repo/target.py.'),
    ]
    fake_which.assert_called_once_with('codex')


def test_invalid_manifest(monkeypatch):
    case = FIXTURES / 'runner/invalid_manifest'
    subprocess_run = Mock()
    mkdir = create_autospec(Path.mkdir)
    monkeypatch.setattr(subprocess, 'run', subprocess_run)
    monkeypatch.setattr(Path, 'mkdir', mkdir)

    result = CliRunner().invoke(
        runner.main, ['run', str(INPUTS / 'invalid.toml')],
        prog_name='agent-runner', catch_exceptions=False,
    )

    assert result.exit_code == 2
    assert result.stdout == ''
    assert result.stderr == (case / 'expected_output.stderr.txt').read_text()
    subprocess_run.assert_not_called()
    mkdir.assert_not_called()


def test_codex_failure(monkeypatch, fake_which, mock_path_writes):
    case = FIXTURES / 'runner/codex_failure'
    manifest = INPUTS / 'in_place.toml'
    repo = manifest.parent / 'repo'
    log_dir = manifest.parent / 'logs' / RUN_ID
    mkdir, write_text, replace = mock_path_writes
    subprocess_run = Mock(return_value=subprocess.CompletedProcess([], 0, HEAD + '\n'))
    codex_run = Mock(return_value=CodexResult(7, ''))
    monkeypatch.setattr(subprocess, 'run', subprocess_run)
    monkeypatch.setattr(runner.Codex, 'run', codex_run)

    result = CliRunner().invoke(
        runner.main, ['run', str(manifest)], prog_name='agent-runner', catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert result.stderr == ''
    assert result.stdout.replace(str(manifest.parent), '<fixture>') == (
        case / 'expected_output.stdout.txt'
    ).read_text()
    assert mkdir.call_args_list == [
        call(log_dir, parents=True),
        call(log_dir, parents=True, exist_ok=True),
    ]
    write_text.assert_called_once_with(
        log_dir / 'metadata.json.tmp', (case / 'expected_output.metadata.json').read_text(),
    )
    replace.assert_called_once_with(log_dir / 'metadata.json.tmp', log_dir / 'metadata.json')
    subprocess_run.assert_called_once_with(
        ['git', 'rev-parse', 'HEAD'], cwd=str(repo), capture_output=True, text=True,
    )
    codex_run.assert_called_once_with('agent-01.1', repo, TASK)
    fake_which.assert_called_once_with('codex')


def test_in_place_continue(tmp_path, monkeypatch, fake_which):
    case = FIXTURES / 'runner/in_place_continue'
    repo = INPUTS / 'repo'
    logs = tmp_path / 'logs'
    log_dir = logs / RUN_ID

    def load(path):
        settings = load_manifest(path)
        if path.parent == INPUTS:
            settings['log_root'] = str(logs)
        return settings

    def run(args, **options):
        if args == ['git', 'rev-parse', 'HEAD']:
            return subprocess.CompletedProcess(args, 0, HEAD + '\n')
        summary = Path(args[args.index('--output-last-message') + 1])
        summary.write_text('{"short_summary":"Simplify the calculation","report":"Validated changes."}\n')
        options['stdout'].write('{"type":"turn.completed"}\n')
        options['stderr'].write('codex diagnostic\n')
        return subprocess.CompletedProcess(args, 0)

    subprocess_run = Mock(side_effect=run)
    monkeypatch.setattr(runner, 'load_manifest', load)
    monkeypatch.setattr(subprocess, 'run', subprocess_run)

    first = CliRunner().invoke(
        runner.main, ['run', str(INPUTS / 'in_place.toml')],
        prog_name='agent-runner', catch_exceptions=False,
    )
    resumed = CliRunner().invoke(
        runner.main, ['run', str(INPUTS / 'continue.toml'), '--continue'],
        prog_name='agent-runner', catch_exceptions=False,
    )

    assert first.exit_code == resumed.exit_code == 0
    assert first.stderr == resumed.stderr == ''
    assert first.stdout.replace(str(tmp_path), '<tmp>') == (case / 'expected_output.stdout.txt').read_text()
    assert resumed.stdout.replace(str(tmp_path), '<tmp>') == (case / 'expected_output.continue.stdout.txt').read_text()
    expected_metadata = read_json(case / 'expected_output.metadata.json')
    expected_metadata['settings']['repo'] = os.path.relpath(repo, log_dir)
    expected_metadata['settings']['build_root'] = os.path.relpath(INPUTS / 'build', log_dir)
    assert read_json(log_dir / 'metadata.json') == expected_metadata

    executable = str(FIXTURES / 'bin/codex')
    depencity = ['run', '--project', str(PROJECT), 'depencity-mcp', '--workspace', str(repo)]
    docker = [
        'run', '--project', str(PROJECT), 'agent-runner-mcp', '--workspace', str(repo),
        '--build-root', str(INPUTS / 'build'), '--dockerfile', 'Dockerfile.test',
    ]
    codex_args = [
        executable, 'exec', '--ephemeral', '--skip-git-repo-check', '--json', '--ignore-user-config',
        '--config', 'mcp_servers.depencity.command="uv"',
        '--config', f'mcp_servers.depencity.args={json.dumps(depencity)}',
        '--config', f'mcp_servers.depencity.cwd={json.dumps(str(repo))}',
        '--config', 'mcp_servers.depencity.default_tools_approval_mode="approve"',
        '--config', 'mcp_servers.depencity.enabled_tools=["profile"]',
        '--config', 'mcp_servers.agent-runner.command="uv"',
        '--config', f'mcp_servers.agent-runner.args={json.dumps(docker)}',
        '--config', f'mcp_servers.agent-runner.cwd={json.dumps(str(repo))}',
        '--config', 'mcp_servers.agent-runner.default_tools_approval_mode="approve"',
        '--config', 'mcp_servers.agent-runner.enabled_tools=["docker"]',
        '--config', 'default_permissions="project"',
        '--config', 'permissions.project.filesystem={ ":root" = "deny", ":minimal" = "read", '
        '":tmpdir" = "deny", ":slash_tmp" = "deny", '
        f'{json.dumps(executable)} = "read", {json.dumps(str(repo))} = "write", '
        f'{json.dumps(str(log_dir))} = "deny" }}',
        '--config', 'permissions.project.network.enabled=false',
        '--config', 'approval_policy="never"',
        '--config', 'web_search="disabled"',
        '--cd', str(repo), '--output-schema',
        str(PROJECT / 'agent_runner/src/agent_runner/codex-output.schema.json'),
    ]
    assert subprocess_run.call_args_list == [
        call(['git', 'rev-parse', 'HEAD'], cwd=str(repo), capture_output=True, text=True),
        call([*codex_args, '--output-last-message', str(log_dir / 'agent-01.1.summary.json'),
              '--model', 'gpt-6-luna', TASK], cwd=repo, stdout=ANY, stderr=ANY),
        call([*codex_args, '--output-last-message', str(log_dir / 'agent-01.2.summary.json'),
              '--model', 'gpt-6-luna', TASK], cwd=repo, stdout=ANY, stderr=ANY),
    ]
    for iteration in (1, 2):
        assert (log_dir / f'agent-01.{iteration}.jsonl').read_text() == '{"type":"turn.completed"}\n'
        assert (log_dir / f'agent-01.{iteration}.stderr.log').read_text() == 'codex diagnostic\n'
        assert read_json(log_dir / f'agent-01.{iteration}.summary.json') == {
            'short_summary': 'Simplify the calculation', 'report': 'Validated changes.',
        }
    assert fake_which.call_args_list == [call('codex'), call('codex')]


@pytest.mark.parametrize(('name', 'variant', 'candidate', 'test_code', 'metric_after'), (
    ('evaluated_accepted', 'depencity', 'answer = 42\n', 0, 2),
    ('evaluated_rejected', 'plain', 'answer = 0\n', 1, None),
    ('metric_regression', 'depencity', 'answer = 21 * 2\n', 0, 5),
), ids=('accepted', 'tests_fail', 'metric_regression'))
def test_evaluated_run(name, variant, candidate, test_code, metric_after, tmp_path, monkeypatch):
    case = FIXTURES / 'runner' / name
    manifest = INPUTS / ('plain.toml' if variant == 'plain' else 'evaluated.toml')
    settings = load_manifest(manifest)
    logs = tmp_path / 'logs'
    settings['log_root'] = str(logs)
    log_dir = logs / RUN_ID
    workspace = log_dir / variant / 'workspace'
    metric = 'graph.paths.expressions.count'

    def run_codex(codex, iteration, directory, task):
        assert codex.with_depencity == (variant == 'depencity')
        assert set(directory.iterdir()) == {directory / 'target.py', directory / 'test_target.py'}
        (directory / 'helper.py').write_text('extra = True')
        (directory / 'target.py').write_text(candidate)
        if test_code:
            (directory / 'test_target.py').write_text('raise AssertionError("modified by agent")\n')
        return CodexResult(0, 'Simplify the calculation')

    codex_run = create_autospec(runner.Codex.run, side_effect=run_codex)
    replies = [
        subprocess.CompletedProcess([], 0, HEAD + '\n'),
        subprocess.CompletedProcess([], 0, json.dumps({'scopes': [
            {'id': '__root__', 'profile': {metric: 4}},
        ]})),
        subprocess.CompletedProcess([], 0, 'image built\n'),
        subprocess.CompletedProcess([], test_code, '1 failed\n' if test_code else '1 passed\n'),
    ]
    if metric_after is not None:
        replies.append(subprocess.CompletedProcess([], 0, json.dumps({'scopes': [
            {'id': '__root__', 'profile': {metric: metric_after}},
        ]})))
    subprocess_run = Mock(side_effect=replies)
    monkeypatch.setattr(runner, 'load_manifest', Mock(return_value=settings))
    monkeypatch.setattr(runner.Codex, 'run', codex_run)
    monkeypatch.setattr(subprocess, 'run', subprocess_run)

    result = CliRunner().invoke(
        runner.main, ['run', str(manifest)], prog_name='agent-runner', catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert result.stderr == ''
    assert result.stdout.replace(str(tmp_path), '<tmp>') == (case / 'expected_output.stdout.txt').read_text()
    assert not codex_run.call_args.args[2].exists()
    assert not (workspace / 'helper.py').exists()
    codex_run.assert_called_once_with(ANY, 'agent-01.1', ANY, TASK + ' Target: target.py. Tests: test_target.py.')

    profile_call = call(
        [str(FIXTURES / 'bin/depencity'), 'profile', '--format', 'json', '--depth', '0',
         str(workspace / 'target.py')], cwd=workspace, capture_output=True, text=True, check=True,
    )
    docker_output = {'text': True, 'stdout': subprocess.PIPE, 'stderr': subprocess.STDOUT}
    build = INPUTS / 'build'
    assert subprocess_run.call_args_list == [
        call(['git', 'rev-parse', 'HEAD'], cwd=str(INPUTS / 'repo'), capture_output=True, text=True),
        profile_call,
        call([str(DOCKER), 'build', '--network', 'default', '--file', 'Dockerfile.test',
              '--tag', 'depencity-test:local', str(build)], cwd=build, **docker_output),
        call(
            [str(DOCKER), 'run', '--rm', '--network', 'none', '--read-only',
             '--tmpfs', '/tmp:rw,exec,nosuid,size=256m', '--cap-drop', 'ALL',
             '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--memory', '2g',
             '--cpus', '2', '--user', '1000:1000', '-e', 'PYTHONDONTWRITEBYTECODE=1',
             '-v', f'{workspace}:/workspace:ro', '-w', '/workspace', 'depencity-test:local',
             'python', '-m', 'pytest', '-q', 'test_target.py', '-p', 'no:cacheprovider'],
            cwd=workspace, **docker_output,
        ),
        *([profile_call] if metric_after is not None else []),
    ]
    expected_artifacts = read_json(case / 'expected_output.files.json')
    expected_metadata = json.loads(expected_artifacts[f'{RUN_ID}/metadata.json'])
    expected_metadata['settings']['repo'] = os.path.relpath(INPUTS / 'repo', log_dir)
    expected_metadata['settings']['build_root'] = os.path.relpath(build, log_dir)
    assert read_json(log_dir / 'metadata.json') == expected_metadata
    del expected_artifacts[f'{RUN_ID}/metadata.json']
    assert {
        path.relative_to(logs).as_posix(): path.read_text().replace(str(tmp_path), '<tmp>')
        for path in (log_dir / variant).rglob('*') if path.is_file()
    } == expected_artifacts
