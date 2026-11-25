"""Independent branches for each worker iteration."""

from agent_runner.runners.worktree import WorktreeRunner


class FreshRunner(WorktreeRunner):
    """Run each iteration in a new branch and temporary worktree."""

    def run_worker(self, name):
        for iteration in range(1, self.iterations + 1):
            if self.stopping:
                break
            with self.git.create_workspace_branch(name, iteration) as branch:
                result = self.run_iteration(name, iteration, branch.work_dir)
                if result.return_code != 0:
                    return False
                if not self.commit_candidate(name, iteration, branch, result.short_summary):
                    branch.discard_candidate()
        return True
