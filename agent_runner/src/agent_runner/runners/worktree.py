"""Shared setup, prompts, and validation for Git worktree workers."""

import json
import shlex
from fractions import Fraction

import click

from agent_runner.extractions import candidate_extraction_failures
from agent_runner.git import Git
from agent_runner.mcp import _docker
from agent_runner.runners.base import Runner


class WorktreeRunner(Runner):
    """Give each worktree worker its own file assignment."""

    def __init__(self, codex, repo, count, task, iterations, run_id, source_files=(), require_unchanged_coverage=False,
                 enforce_extraction_path_limits=False):
        super().__init__(codex, repo, count, task, iterations)
        self.git = Git(repo, run_id)
        self.require_unchanged_coverage = require_unchanged_coverage
        self.enforce_extraction_path_limits = enforce_extraction_path_limits
        self.baseline_coverage = None
        self.file_assignments = {
            f'agent-{index + 1:02d}': source_files[index::count] or [source_files[index % len(source_files)]]
            for index in range(count)
        } if source_files else {}

    def run(self):
        if self.require_unchanged_coverage:
            self.baseline_coverage = self.measure_coverage(self.repo, 'baseline')
        return super().run()

    def commit_candidate(self, name, iteration, branch, summary):
        if self.enforce_extraction_path_limits:
            failures = list(candidate_extraction_failures(branch.work_dir))
            if failures:
                for failure in failures:
                    click.echo(f'{name}.{iteration}: rejected extraction: {failure}')
                return False
        if self.baseline_coverage is not None:
            label = f'{name}.{iteration}'
            if self.measure_coverage(branch.work_dir, label) != self.baseline_coverage:
                click.echo(f'{label}: coverage changed from baseline; leaving candidate uncommitted')
                return False
        branch.commit(summary)
        return True

    def measure_coverage(self, workspace, label):
        report = '/tmp/agent-runner-coverage.json'
        command = shlex.join([
            'sh', '-c', f'"$@" && cat {report}', 'coverage-check',
            'env', 'COVERAGE_FILE=/tmp/.coverage', 'pytest', '-q', 'agent_runner/tests',
            '-p', 'no:cacheprovider', '--import-mode=importlib', '-n', '2',
            '--cov=agent_runner/src/agent_runner',
            '--cov-branch', f'--cov-report=json:{report}',
        ])
        result = json.loads(_docker(
            '.', workspace, self.codex.build_root,
            self.codex.build_root / self.codex.dockerfile, command,
        ))
        log = self.codex.log_dir / f'{label}.coverage.log'
        log.write_text(result['output'])
        if result['returncode']:
            raise click.ClickException(f'{label}: coverage check failed; see {log}')
        totals = json.loads(result['output'].splitlines()[-1])['totals']
        return (
            Fraction(totals['missing_lines'], totals['num_statements'] or 1),
            Fraction(totals['missing_branches'], totals['num_branches'] or 1),
        )

    def worker_prompt(self, name):
        assigned = self.file_assignments.get(name)
        if assigned:
            return f'{self.task} Refactor only these source files, in order: {", ".join(assigned)}.'
        return super().worker_prompt(name)
