"""Cumulative iterations in one workspace per worker."""

from agent_runner.runners.worktree import WorktreeRunner


class IncrementalRunner(WorktreeRunner):
    """Keep each worker's branch and worktree open across iterations."""

    def run_worker(self, name):
        with self.git.create_workspace_branch(name, 1) as branch:
            for iteration in range(1, self.iterations + 1):
                result = self.run_iteration(name, iteration, branch.work_dir)
                if result.return_code != 0:
                    return False
                if not self.commit_candidate(name, iteration, branch, result.short_summary):
                    branch.discard_candidate()
                if self.stopping:
                    break
        return True
