"""MCP tool for Docker testing."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import click
from fastmcp import Context, FastMCP
from fastmcp.server.lifespan import lifespan

from .docker_test import (
    DEFAULT_BUILD_IMAGE,
    docker_build_command,
    docker_command,
    docker_daemon_unavailable,
    run_docker,
)


@click.command(name='agent-runner-mcp')
@click.option('--workspace', type=click.Path(path_type=Path), default='.', show_default=True)
@click.option('--build-root', type=click.Path(path_type=Path), required=True)
@click.option('--dockerfile', type=click.Path(path_type=Path), required=True)
@click.option('--image', default=DEFAULT_BUILD_IMAGE, show_default=True)
def main(
    workspace: Path,
    build_root: Path,
    dockerfile: Path,
    image: str,
) -> None:
    workspace_root = workspace.resolve()
    build_root = build_root.resolve()
    try:
        dockerfile = _inside(build_root, dockerfile)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    if not dockerfile.is_file():
        raise click.ClickException(f'Dockerfile does not exist: {dockerfile}')
    create_server(workspace_root, build_root, dockerfile, image).run()


def create_server(
    workspace_root: Path,
    build_root: Path,
    dockerfile: Path,
    image: str = DEFAULT_BUILD_IMAGE,
) -> FastMCP:
    @lifespan
    async def app_lifespan(_server):
        yield {
            'workspace_root': workspace_root,
            'build_root': build_root,
            'dockerfile': dockerfile,
            'image': image,
        }

    mcp = FastMCP('agent-runner', lifespan=app_lifespan)
    mcp.tool(docker_test)
    return mcp


async def docker_test(
    ctx: Context,
    path: str,
    command: str | None = None,
) -> str:
    config = ctx.lifespan_context
    return await asyncio.to_thread(
        _docker_test,
        path,
        config['workspace_root'],
        config['build_root'],
        config['dockerfile'],
        command,
        config['image'],
    )


def _docker_test(
    path: str,
    workspace_root: Path,
    build_root: Path,
    dockerfile: Path,
    command: str | None = None,
    image: str = DEFAULT_BUILD_IMAGE,
) -> str:
    target = _inside(workspace_root, path)
    executable = shutil.which('docker') or str(Path.home() / '.docker' / 'bin' / 'docker')
    if not Path(executable).exists():
        raise RuntimeError('Docker executable not found on PATH or in ~/.docker/bin')

    build_args = docker_build_command(build_root, dockerfile, image, executable)
    build = _run_docker(build_args, build_root, 'Docker image build')
    if build.returncode:
        raise RuntimeError(f'Docker image build failed: {build.stdout.strip()}')
    command_args = docker_command(target, workspace_root, image, command, executable)
    result = _run_docker(command_args, workspace_root, 'Docker test')
    return json.dumps({
        'returncode': result.returncode,
        'output': result.stdout,
    }, sort_keys=True)


def _run_docker(
    command_args: list[str],
    workspace: Path,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = run_docker(command_args, workspace)
    except OSError as error:
        raise RuntimeError(f'{operation} could not start: {error}') from error
    if result.returncode and docker_daemon_unavailable(result.stdout):
        raise RuntimeError(f'Docker daemon is unavailable: {result.stdout.strip()}')
    return result


def _inside(root: Path, value: str | Path) -> Path:
    path = (root / Path(value)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f'path must be inside workspace: {root}') from error
    return path
