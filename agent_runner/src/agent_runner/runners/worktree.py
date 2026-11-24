"""Shared setup and prompts for Git worktree workers."""

from agent_runner.git import Git
from agent_runner.runners.base import Runner


class WorktreeRunner(Runner):
    """Give each worktree worker its own file assignment."""

    def __init__(self, codex, repo, count, task, iterations, run_id, source_files=()):
        super().__init__(codex, repo, count, task, iterations)
        self.git = Git(repo, run_id)
        self.file_assignments = {
            f'agent-{index + 1:02d}': source_files[index::count] or [source_files[index % len(source_files)]]
            for index in range(count)
        } if source_files else {}

    def worker_prompt(self, name):
        assigned = self.file_assignments.get(name)
        if assigned:
            return f'{self.task} Refactor only these source files, in order: {", ".join(assigned)}.'
        return super().worker_prompt(name)
