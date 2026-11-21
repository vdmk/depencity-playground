import subprocess
from unittest.mock import Mock, call

import pytest
from click.testing import CliRunner
from fastmcp import Client, __version__ as fastmcp_version

from agent_runner import mcp

from .utils import DOCKER, FIXTURES, read_json


pytestmark = pytest.mark.usefixtures('fake_which')



@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ('asyncio',))
@pytest.mark.parametrize(('name', 'replies', 'test_command'), (
    ('default_command', ((0, 'image built\n'), (0, 'hello\n')), ['python', 'task.py']),
    ('failing_test', ((0, 'image built\n'), (5, 'no tests ran\n')), ['python', '-c', 'print(42)']),
    ('build_failure', ((1, 'invalid Dockerfile\n'),), None),
    ('launch_error', (OSError('cannot execute docker'),), None),
    ('daemon_unavailable', ((1, 'cannot connect to docker.sock\n'),), None),
    ('outside_workspace', (), None),
))
async def test_docker_matches_mcp_contract(name, replies, test_command, monkeypatch, fake_which):
    case = FIXTURES / 'mcp' / name
    build_root = case.parent / 'startup'
    run = Mock(side_effect=[
        reply if isinstance(reply, OSError) else subprocess.CompletedProcess([], *reply)
        for reply in replies
    ])
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=AssertionError('unexpected subprocess')))
    monkeypatch.setattr(subprocess, 'run', run)
    server = mcp.create_server(case, build_root, build_root / 'Dockerfile', 'snapshot:test')
    request_dir = case if name in ('failing_test', 'outside_workspace') else case.parent
    request = read_json(request_dir / 'input.mcp.json')

    async with Client(server) as client:
        tools = await client.list_tools()
        result = await client.call_tool_mcp(**request)
    response = result.model_dump(mode='json', by_alias=True, exclude_none=True)
    server_info = response['_meta']['io.modelcontextprotocol/serverInfo']
    server_info['version'] = server_info['version'].replace(fastmcp_version, '<fastmcp-version>')
    for item in response['content']:
        if 'text' in item:
            item['text'] = item['text'].replace(str(case), '<case>')

    assert [tool.model_dump(mode='json', exclude_none=True) for tool in tools] == read_json(
        case.parent / 'expected_output.tools.json',
    )
    assert response == read_json(case / 'expected_output.mcp.json')
    expected_calls = []
    if replies:
        fake_which.assert_called_once_with('docker')
        expected_calls.append(call(
            [str(DOCKER), 'build', '--network', 'default', '--file', 'Dockerfile',
             '--tag', 'snapshot:test', '--build-context', f'depencity={case.parent / "depencity"}',
             str(build_root)],
            cwd=build_root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ))
    else:
        fake_which.assert_not_called()
    if test_command:
        expected_calls.append(call(
            [str(DOCKER), 'run', '--rm', '--network', 'none', '--read-only',
             '--tmpfs', '/tmp:rw,exec,nosuid,size=256m', '--cap-drop', 'ALL',
             '--security-opt', 'no-new-privileges', '--pids-limit', '256', '--memory', '2g',
             '--cpus', '2', '--user', '1000:1000', '-e', 'PYTHONDONTWRITEBYTECODE=1',
             '-v', f'{case}:/workspace:ro', '-w', '/workspace', 'snapshot:test',
             *test_command],
            cwd=case, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        ))
    assert run.call_args_list == expected_calls


@pytest.mark.parametrize(('name', 'exit_code'), (('startup', 0), ('outside_build_root', 1)))
def test_mcp_cli_matches_contract(name, exit_code, monkeypatch):
    case = FIXTURES / 'mcp' / name
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=AssertionError('unexpected subprocess')))
    create_server = Mock()
    monkeypatch.setattr(mcp, 'create_server', create_server)
    monkeypatch.chdir(case)

    result = CliRunner().invoke(mcp.main, read_json(case / 'input.cli.json'), catch_exceptions=False)

    assert result.exit_code == exit_code
    assert result.stdout == ''
    if exit_code == 0:
        assert result.stderr == ''
        create_server.assert_called_once_with(
            case.parent, case, case / 'Dockerfile', 'snapshot:test',
        )
        create_server.return_value.run.assert_called_once_with()
    else:
        assert result.stderr.replace(str(case), '<case>') == (
            case / 'expected_output.stderr.txt'
        ).read_text()
        create_server.assert_not_called()


def test_mcp_cli_rejects_missing_dockerfile(monkeypatch):
    case = FIXTURES / 'mcp/startup'
    create_server = Mock()
    monkeypatch.setattr(mcp, 'create_server', create_server)

    result = CliRunner().invoke(
        mcp.main, ['--build-root', str(case), '--dockerfile', 'missing'], catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert result.stderr == f'Error: Dockerfile does not exist: {case / "missing"}\n'
    create_server.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ('asyncio',))
async def test_mcp_reports_missing_docker_executable(tmp_path, monkeypatch, fake_which):
    case = FIXTURES / 'mcp/startup'
    fake_which.side_effect = None
    fake_which.return_value = None
    monkeypatch.setattr(mcp.Path, 'home', lambda: tmp_path)
    run = Mock()
    monkeypatch.setattr(subprocess, 'run', run)
    server = mcp.create_server(case, case, case / 'Dockerfile')

    async with Client(server) as client:
        result = await client.call_tool_mcp('docker', {'path': 'task.py'})

    assert result.is_error
    assert result.content[0].text.endswith('Docker executable not found on PATH or in ~/.docker/bin')
    run.assert_not_called()
