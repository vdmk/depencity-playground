"""Cumulative iterations directly in the supplied directory."""

from .base import Runner


class SequentialRunner(Runner):
    """Run iterations in place without creating branches or commits."""

    def __init__(self, codex, repo, task, iterations):
        super().__init__(codex, repo, 1, task, iterations)

    def run_worker(self, name):
        for iteration in range(1, self.iterations + 1):
            result = self.run_iteration(name, iteration, self.repo)
            if result.return_code != 0:
                return False
            if self.stopping:
                break
        return True
