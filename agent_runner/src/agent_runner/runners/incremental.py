"""Cumulative iterations in one workspace per worker."""

from ..git import Git
from .base import Runner


class IncrementalRunner(Runner):
    """Keep each worker's branch and worktree open across iterations."""

    def __init__(self, codex, repo, count, task, iterations, run_id):
        super().__init__(codex, repo, count, task, iterations)
        self.git = Git(repo, run_id)

    def run_worker(self, name):
        with self.git.create_workspace_branch(name, 1) as branch:
            for iteration in range(1, self.iterations + 1):
                result = self.run_iteration(name, iteration, branch.work_dir)
                if result.return_code != 0:
                    return False
                branch.commit(result.short_summary)
                if self.stopping:
                    break
        return True
