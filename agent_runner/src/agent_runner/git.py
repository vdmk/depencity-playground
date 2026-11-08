"""Manage temporary worktrees while preserving their branches."""

import subprocess
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import click


BRANCH_PREFIX = 'codex-batch'


class Branch:
    """An isolated working directory that can commit its changes."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = work_dir

    def commit(self, message: str):
        if not run_git(self.work_dir, 'status', '--porcelain'):
            return
        run_git(self.work_dir, 'add', '--all')
        message = f'auto-refactor: {message}'
        run_git(self.work_dir, 'commit', '-m', message)
        click.echo(f'Committed changes: {message}')

class Git:
    """Create temporary worktrees and preserve branches and uncommitted edits."""

    def __init__(self, repo: Path, run_id: str) -> None:
        if run_git(repo, 'status', '--porcelain'):
            raise ValueError('repository must be clean so all agents start from the same commit')
        self.repo = repo
        self.root = repo / '.worktrees' / BRANCH_PREFIX / run_id
        self.base = run_git(repo, 'rev-parse', 'HEAD')
        self.base_ref = run_git(repo, 'rev-parse', '--symbolic-full-name', 'HEAD')
        self.lock = Lock()

    @contextmanager
    def create_workspace_branch(self, name, iteration):
        base = self.base
        if iteration > 1 and self.base_ref != 'HEAD':
            base = run_git(self.repo, 'rev-parse', self.base_ref)
        with self.lock:
            workspace = create_worktree(self.repo, self.root, name, iteration, base)
        try:
            yield Branch(workspace)
        finally:
            dirty = bool(run_git(workspace, 'status', '--porcelain'))
            if not dirty:
                with self.lock:
                    run_git(self.repo, 'worktree', 'remove', str(workspace))
                    click.echo(f'Deleted worktree: {workspace}; branch preserved')
            else:
                click.echo(f'Preserving worktree with uncommitted changes: {workspace}')
        if dirty:
            raise OSError(f'uncommitted changes; preserving worktree: {workspace}')


def create_worktree(repo, root, name, iteration, base):
    branch = f'{BRANCH_PREFIX}/{root.name}/{name}/iteration-{iteration}'
    workspace = root / name / f'iteration-{iteration}'
    workspace.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo, 'worktree', 'add', '-b', branch, str(workspace), base)
    click.echo(f'Created worktree: {workspace}; branch={branch} base={base}')
    return workspace


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ['git', '-C', str(repo), *args], text=True, stderr=subprocess.PIPE,
    ).strip()
