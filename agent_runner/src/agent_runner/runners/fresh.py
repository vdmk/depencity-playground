"""Independent branches for each worker iteration."""

from agent_runner.git import Git
from agent_runner.runners.base import Runner


class FreshRunner(Runner):
    """Run each iteration in a new branch and temporary worktree."""

    def __init__(self, codex, repo, count, task, iterations, run_id):
        super().__init__(codex, repo, count, task, iterations)
        self.git = Git(repo, run_id)

    def run_worker(self, name):
        for iteration in range(1, self.iterations + 1):
            if self.stopping:
                break
            with self.git.create_workspace_branch(name, iteration) as branch:
                result = self.run_iteration(name, iteration, branch.work_dir)
                if result.return_code != 0:
                    return False
                branch.commit(result.short_summary)
        return True
