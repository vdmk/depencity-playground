"""MCP tools for testing and committing within one agent worktree."""

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
    ledger = build_root / 'agent-runner-files' / 'reviewed.jsonl'
    @lifespan
    async def app_lifespan(_server):
        yield {
            'workspace_root': workspace_root,
            'build_root': build_root,
            'dockerfile': dockerfile,
            'image': image,
            'ledger': ledger.resolve(),
        }

    mcp = FastMCP('agent-runner', lifespan=app_lifespan)
    mcp.tool(docker_test)
    mcp.tool(git_commit)
    mcp.tool(reviewed_commits)
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


async def git_commit(ctx: Context, message: str) -> str:
    """Commit all tracked and untracked changes in this worktree.

    Equivalent to `git add -A && git commit -m`; inspect and test all changes first.
    """
    return await asyncio.to_thread(
        _git_commit,
        ctx.lifespan_context['workspace_root'],
        message,
    )


async def reviewed_commits(ctx: Context, query: str | None = None) -> str:
    """Search the coordinator's local review ledger without modifying it."""
    return await asyncio.to_thread(
        _reviewed_commits,
        ctx.lifespan_context['ledger'],
        query,
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


def _git_commit(workspace: Path, message: str) -> str:
    if not message.strip():
        raise ValueError('a commit message is required')

    root = Path(_git_output(workspace, 'rev-parse', '--show-toplevel')).resolve()
    if root != workspace or not (workspace / '.git').is_file():
        raise ValueError('MCP workspace must be a linked Git worktree root')
    if not _git_output(workspace, 'branch', '--show-current').startswith('codex-batch/'):
        raise ValueError('commits are allowed only on codex-batch worktree branches')
    _git_output(workspace, 'add', '--all')
    _git_output(
        workspace,
        '-c', 'core.hooksPath=/dev/null',
        '-c', 'commit.gpgsign=false',
        'commit', '-m', message,
    )
    return _git_output(workspace, 'rev-parse', '--short', 'HEAD')


def _reviewed_commits(ledger: Path | None, query: str | None) -> str:
    records = _read_review_records(ledger)
    if query:
        records = [
            record for record in records
            if query.lower() in json.dumps(record, sort_keys=True).lower()
        ]
    return json.dumps(records, sort_keys=True)


def _read_review_records(ledger: Path | None) -> list[dict]:
    if ledger is None or not ledger.is_file():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line]


def _git_output(workspace: Path, *args: str) -> str:
    return subprocess.run(
        ['git', '-C', str(workspace), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _inside(root: Path, value: str | Path) -> Path:
    path = (root / Path(value)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError(f'path must be inside workspace: {root}') from error
    return path
