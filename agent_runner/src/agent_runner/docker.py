"""Run a guinea-pig program in a constrained Docker container."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path


DEFAULT_BUILD_IMAGE = 'depencity-test:local'


def docker_command(
    target: Path,
    workspace: Path,
    image: str,
    command: str | None,
    executable: str = 'docker',
) -> list[str]:
    relative_target = target.relative_to(workspace)
    test_command = shlex.split(command) if command else ['python', str(relative_target)]
    return [
        executable, 'run', '--rm',
        '--network', 'none',
        '--read-only',
        '--tmpfs', '/tmp:rw,exec,nosuid,size=256m',
        '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges',
        '--pids-limit', '256',
        '--memory', '2g',
        '--cpus', '2',
        '--user', '1000:1000',
        '-e', 'PYTHONDONTWRITEBYTECODE=1',
        '-v', f'{workspace}:/workspace:ro',
        '-w', '/workspace',
        image,
        *test_command,
    ]


def docker_build_command(
    workspace: Path,
    dockerfile: Path,
    image: str,
    executable: str = 'docker',
) -> list[str]:
    command = [
        executable, 'build',
        '--network', 'default',
        '--file', str(dockerfile.relative_to(workspace)),
        '--tag', image,
    ]
    depencity = workspace.parent / 'depencity'
    if depencity.is_dir():
        command.extend(['--build-context', f'depencity={depencity}'])
    return [*command, str(workspace)]


def run_docker(
    command: list[str],
    workspace: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def docker_daemon_unavailable(output: str) -> bool:
    output = output.lower()
    return (
        'docker.sock' in output
        or 'docker daemon' in output
        or 'permission denied' in output
    )
