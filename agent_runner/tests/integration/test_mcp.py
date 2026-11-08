import asyncio
import json
import subprocess
import threading
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastmcp import Client

import agent_runner.mcp as runner_mcp
from agent_runner.mcp import _docker, create_server as create_runner_server
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mcp_cli_passes_click_options_to_server(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    build_root = tmp_path / 'trusted-build'
    build_root.mkdir()
    (build_root / 'Dockerfile.test').write_text('FROM scratch\n')
    calls = []
    monkeypatch.chdir(workspace)

    class Server:
        def run(self):
            calls.append('run')

    def create_server(root, build, dockerfile, image):
        calls.append((root, build, dockerfile, image, Path.cwd()))
        return Server()

    monkeypatch.setattr(runner_mcp, 'create_server', create_server)
    result = CliRunner().invoke(runner_mcp.main, [
        '--build-root', str(build_root),
        '--dockerfile', 'Dockerfile.test',
        '--workspace', str(workspace),
        '--image', 'complexity:test',
    ])

    assert result.exit_code == 0
    assert calls == [
        (workspace, build_root, build_root / 'Dockerfile.test', 'complexity:test', workspace),
        'run',
    ]


def test_mcp_cli_rejects_dockerfile_outside_build_root(tmp_path):
    build_root = tmp_path / 'trusted-build'
    build_root.mkdir()
    outside = tmp_path / 'outside.Dockerfile'
    outside.write_text('FROM scratch\n')

    result = CliRunner().invoke(runner_mcp.main, [
        '--workspace', str(tmp_path),
        '--build-root', str(build_root),
        '--dockerfile', str(outside),
    ])

    assert result.exit_code == 1
    assert 'path must be inside workspace' in result.output


def test_runner_mcp_exposes_only_docker():
    import asyncio

    runner_tools = asyncio.run(
        create_runner_server(REPO_ROOT, REPO_ROOT, REPO_ROOT / "docker/test/Dockerfile").list_tools()
    )

    assert {tool.name for tool in runner_tools} == {
        "docker",
    }


def test_mcp_docker_tool_runs_through_fake_docker(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nprintf '%s\\n' 'ok'\n")
    docker.chmod(0o755)
    target = tmp_path / "task.py"
    target.write_text("print('ok')\n")
    dockerfile = tmp_path / "Dockerfile.test"
    dockerfile.write_text("FROM scratch\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    result = json.loads(_docker("task.py", tmp_path, tmp_path, dockerfile))

    assert result["returncode"] == 0
    assert result["output"] == "ok\n"


def test_mcp_docker_tool_builds_test_image_before_running(tmp_path, monkeypatch):
    capture = tmp_path / "docker-calls"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_CAPTURE\"\n"
        "printf 'ok\\n'\n"
    )
    docker.chmod(0o755)
    (tmp_path / "Dockerfile.test").write_text("FROM scratch\n")
    (tmp_path / "task.py").write_text("print('ok')\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("DOCKER_CAPTURE", str(capture))
    monkeypatch.chdir(tmp_path)

    json.loads(
        _docker(
            "task.py",
            tmp_path,
            tmp_path,
            tmp_path / "Dockerfile.test",
        )
    )

    build_call, run_call = capture.read_text().splitlines()
    assert "--network default" in build_call
    assert "--network none" in run_call


def test_mcp_docker_tool_uses_startup_build_config_outside_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    worktree = repo / ".worktrees" / "agent"
    worktree.mkdir(parents=True)
    configured_dockerfile = repo / "Dockerfile.test"
    configured_dockerfile.write_text("FROM configured\n")
    (worktree / "Dockerfile.test").write_text("FROM agent-controlled\n")
    (worktree / "task.py").write_text("print('ok')\n")
    capture = tmp_path / "docker-calls"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_CAPTURE\"\n"
        "if [ \"$1\" = build ]; then printf 'trusted build\\n'; "
        "else printf 'test run\\n'; fi\n"
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("DOCKER_CAPTURE", str(capture))
    monkeypatch.chdir(worktree)

    server = create_runner_server(
        worktree, repo, configured_dockerfile, "complexity-test:agent"
    )

    async def call_tool():
        async with Client(server) as client:
            return await client.call_tool("docker", {"path": "task.py"})

    response = asyncio.run(call_tool())
    result = json.loads(response.content[0].text)
    build_call, run_call = capture.read_text().splitlines()

    assert result["returncode"] == 0
    assert "--file Dockerfile.test" in build_call
    assert "--tag complexity-test:agent" in build_call
    assert build_call.endswith(str(repo))
    assert str(worktree) in run_call
    assert "complexity-test:agent" in run_call


def test_mcp_docker_tool_reports_daemon_failure(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'permission denied while trying to connect to docker.sock'\nexit 1\n"
    )
    docker.chmod(0o755)
    target = tmp_path / "task.py"
    target.write_text("print('ok')\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="Docker daemon is unavailable"):
        _docker("task.py", tmp_path, tmp_path, tmp_path / "Dockerfile.test")


def test_mcp_docker_tool_requires_docker(tmp_path, monkeypatch):
    target = tmp_path / "task.py"
    target.write_text("print('ok')\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="Docker executable not found"):
        _docker("task.py", tmp_path, tmp_path, tmp_path / "Dockerfile.test")


def test_mcp_docker_tool_reports_launch_error(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text("not an executable format")
    docker.chmod(0o755)
    target = tmp_path / "task.py"
    target.write_text("print('ok')\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="Docker image build could not start"):
        _docker("task.py", tmp_path, tmp_path, tmp_path / "Dockerfile.test")


def test_mcp_docker_tools_run_concurrently(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nprintf '%s\\n' 'ok'\n")
    docker.chmod(0o755)
    (tmp_path / "Dockerfile.test").write_text("FROM scratch\n")
    (tmp_path / "task.py").write_text("print('ok')\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    barrier = threading.Barrier(2)

    def fake_run(command, workspace):
        barrier.wait(timeout=1)
        return subprocess.CompletedProcess(command, 0, "ok\n")

    monkeypatch.setattr("agent_runner.mcp.run_docker", fake_run)

    async def run_both():
        async with Client(
            create_runner_server(
                tmp_path, tmp_path, tmp_path / "Dockerfile.test"
            )
        ) as client:
            return await asyncio.gather(
                client.call_tool("docker", {"path": "task.py"}),
                client.call_tool("docker", {"path": "task.py"}),
            )

    results = [
        json.loads(result.content[0].text)
        for result in asyncio.run(run_both())
    ]

    assert [result["returncode"] for result in results] == [0, 0]
