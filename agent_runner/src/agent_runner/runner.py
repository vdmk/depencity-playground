"""Run independent Codex refactoring agents in Git worktrees."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import click


BRANCH_PREFIX = 'codex-batch'
SOURCE_ROOTS = (
    Path('depencity/src/depencity'),
    Path('agent_runner/src/agent_runner'),
)
DEFAULT_TASK = (
    'Inspect the compact profile for the whole module or package and make one '
    'coherent structural refactoring across a workflow or repeated concept. '
    'Do not settle for an isolated syntax edit or enlarge the diff for its own '
    'sake. Apply analogous cases one by one when each improves the code and '
    'profile. Use a different perspective on each iteration. If small '
    'refactorings do not work, try a larger coherent refactoring. '
    'Follow the profile, test, and commit loop in AGENTS.md. Do not merge or '
    'cherry-pick.'
)


@click.command()
@click.option('--repo', type=click.Path(path_type=Path), default=Path.cwd)
@click.option('--count', type=click.IntRange(1, 100), default=5, show_default=True, help='Number of parallel agents.')
@click.option('--iterations', type=click.IntRange(1, 100), default=1, show_default=True, help='Maximum iterations per agent.')
@click.option('--task', default=DEFAULT_TASK, show_default=False, help='Shared refactoring task for every agent.')
@click.option('--model', default='gpt-6-luna', show_default=True, help='Codex model.')
def main(repo: Path, count: int, iterations: int, task: str, model: str) -> None:
    try:
        successful = run(repo, count, task, model, iterations)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise click.ClickException(str(error)) from error
    if not successful:
        raise click.exceptions.Exit(1)


def run(
    repo: Path,
    count: int,
    task: str,
    model: str,
    iterations: int = 1,
) -> bool:
    repo = repo.resolve()
    if _run_git(repo, 'status', '--porcelain'):
        raise ValueError('repository must be clean so all agents start from the same commit')
    if not (repo / 'AGENTS.md').is_file():
        raise ValueError('repository root must contain AGENTS.md')
    source_files = sorted(
        path.relative_to(repo).as_posix()
        for source_root in SOURCE_ROOTS
        for path in (repo / source_root).rglob('*.py')
        if path.name != '__init__.py'
    )
    if not source_files:
        raise ValueError(f'no Python source files found under {SOURCE_ROOTS}')
    codex = shutil.which('codex')
    if not codex:
        raise ValueError('codex CLI was not found; add it to PATH')

    base = _run_git(repo, 'rev-parse', 'HEAD')
    base_ref = _run_git(repo, 'rev-parse', '--symbolic-full-name', 'HEAD')
    if base_ref == 'HEAD':
        base_ref = None
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}'

    worktree_root = repo / '.worktrees' / BRANCH_PREFIX / run_id
    log_root = repo / 'agent-runner-files' / 'logs' / run_id
    worktree_root.mkdir(parents=True)
    log_root.mkdir(parents=True)

    stopping = False

    def handle_interrupt(_signum, _frame):
        nonlocal stopping
        if stopping:
            raise KeyboardInterrupt
        stopping = True
        click.echo('Stopping after current runs; press Ctrl+C again to interrupt the runner.')

    previous_handler = signal.signal(signal.SIGINT, handle_interrupt)
    worktree_lock = Lock()
    try:
        with ThreadPoolExecutor(max_workers=count) as workers:
            def evolve(name, assigned_files):
                iteration = 0
                (worktree_root / name).mkdir(parents=True, exist_ok=True)
                while not stopping and iteration < iterations:
                    iteration += 1
                    start = (iteration - 1) % len(assigned_files)
                    scan_order = assigned_files[start:] + assigned_files[:start]
                    agent_task = (
                        f'{task} Refactor only these source files, in order: '
                        f'{", ".join(scan_order)}. '
                    )
                    iteration_base = base
                    if iteration > 1 and base_ref is not None:
                        iteration_base = _run_git(repo, 'rev-parse', base_ref)
                    click.echo(f'{name}: iteration {iteration} base={iteration_base}')
                    with worktree_lock:
                        worktree = _create_worktree(
                            repo, worktree_root, name, iteration, iteration_base,
                        )
                    returncode = _run_agent(
                        name, iteration, worktree, repo, log_root,
                        codex, agent_task, model,
                        f'{BRANCH_PREFIX}/{run_id}/{name}/iteration-{iteration}',
                    )
                    if returncode != 0:
                        click.echo(f'{name}: stopped after nonzero exit')
                        return False
                    if stopping:
                        return True
                    if _run_git(worktree, 'status', '--porcelain'):
                        click.echo(f'{name}: stopped with uncommitted changes; preserving worktree')
                        return False
                    commit = _run_git(worktree, 'rev-parse', 'HEAD')
                    if commit != iteration_base:
                        click.echo(
                            f'{name}: committed {commit[:7]}; '
                            'next iteration gets a fresh worktree'
                        )
                return not stopping

            successful = _run_workers(workers, count, source_files, evolve)
            if stopping:
                click.echo('All current runs stopped; not relaunching agents.')
                return True
            click.echo('No agents remain; stopping.')
            return successful
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def _run_workers(workers, count: int, source_files: list[str], evolve) -> bool:
    futures = {}
    for agent_number in range(1, count + 1):
        name = f'agent-{agent_number:02d}'
        assigned_files = source_files[agent_number - 1::count] or [
            source_files[(agent_number - 1) % len(source_files)]
        ]
        futures[workers.submit(evolve, name, assigned_files)] = name
    successful = True
    for future in as_completed(futures):
        name = futures[future]
        try:
            successful &= future.result()
        except (OSError, subprocess.CalledProcessError) as error:
            click.echo(f'{name}: stopped after runner error ({error})')
            successful = False
    return successful


def _create_worktree(
    repo: Path,
    root: Path,
    name: str,
    iteration: int,
    base: str,
) -> Path:
    branch = f'{BRANCH_PREFIX}/{root.name}/{name}/iteration-{iteration}'
    worktree = root / name / f'iteration-{iteration}'
    _run_git(repo, 'worktree', 'add', '-b', branch, str(worktree), base)
    return worktree


def _run_agent(
    name,
    run_index: int,
    worktree: Path,
    repo: Path,
    log_root: Path,
    codex: str,
    task: str,
    model: str,
    branch: str,
) -> int:
    stdout_log = log_root / f'{name}.{run_index}.jsonl'
    stderr_log = log_root / f'{name}.{run_index}.stderr.log'
    click.echo(
        f'Launching {name} run {run_index}: branch={branch} worktree={worktree} '
        f'stdout={stdout_log} stderr={stderr_log}'
    )
    command = [
        codex,
        'exec',
        '--ephemeral',
        '--json',
        '--ignore-user-config',
    ]
    command.extend(_create_mcp_server_options(
        'depencity', [
            'run', '--project', str(repo), 'depencity-mcp',
            '--workspace', str(worktree),
        ], worktree,
    ))
    command.extend(_create_mcp_server_options(
        'agent-runner', [
            'run', '--project', str(repo), 'agent-runner-mcp',
            '--workspace', str(worktree),
            '--build-root', str(repo),
            '--dockerfile', 'docker/test/Dockerfile',
        ], worktree, ['docker_test', 'git_commit', 'reviewed_commits'],
    ))
    command.extend([
        '--sandbox',
        'workspace-write',
        '--config',
        'approval_policy="on-request"',
        '--cd',
        str(worktree),
        '--model',
        model,
        task,
    ])
    with stdout_log.open('w') as stdout:
        with stderr_log.open('w') as stderr:
            result = subprocess.run(command, cwd=worktree, stdout=stdout, stderr=stderr)
    click.echo(f'{name} run {run_index}: finished with return code {result.returncode}')
    return result.returncode


def _create_mcp_server_options(
    name: str,
    arguments: list[str],
    worktree: Path,
    enabled_tools: list[str] | None = None,
) -> list[str]:
    server = f'mcp_servers.{name}'
    options = [
        '--config',
        f'{server}.command="uv"',
        '--config',
        f'{server}.args=' + json.dumps(arguments),
        '--config',
        f'{server}.cwd={json.dumps(str(worktree))}',
        '--config',
        f'{server}.default_tools_approval_mode="approve"',
    ]
    if enabled_tools is not None:
        options.extend([
            '--config',
            f'{server}.enabled_tools=' + json.dumps(enabled_tools),
        ])
    return options


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ['git', '-C', str(repo), *args],
        text=True,
        stderr=subprocess.PIPE,
    ).strip()


if __name__ == '__main__':
    main()
