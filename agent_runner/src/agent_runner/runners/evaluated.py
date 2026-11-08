"""Cumulative refactoring with tests, measurements, and accepted snapshots."""

import shutil

import click

from agent_runner.codex import CodexResult
from agent_runner.evaluator import Evaluator
from agent_runner.runners.in_place import InPlaceRunner


class EvaluatedRunner(InPlaceRunner):
    """Evaluate each candidate before starting the next iteration."""

    def __init__(self, codex, repo, task, iterations, target, metrics, test_script,
                 *, workspace=None, resume=False):
        target = (repo / target).resolve().relative_to(repo)
        test_script = (repo / test_script).resolve().relative_to(repo)
        workspace = workspace or codex.log_dir / 'workspace'
        for relative_path in (target, test_script):
            if not resume or relative_path == test_script:
                destination = workspace / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / relative_path, destination)
        super().__init__(codex, workspace, task, iterations)
        self.evaluator = Evaluator(workspace, target, metrics, test_script)
        self.task += f' Target: {target}. Tests: {test_script}.'

    def run_iteration(self, name, iteration, work_dir):
        before = self.evaluator.snapshot()
        try:
            result = super().run_iteration(name, iteration, work_dir)
            report = self.evaluator.evaluate(
                before, self.codex.log_dir / f'{name}.{iteration}', result.return_code,
            )
        except BaseException:
            self.evaluator.target.write_bytes(before.source)
            raise
        click.echo(
            f'{name}.{iteration}: {report["status"]}; '
            f'{report["metrics"]}: {report["before"]} -> {report["after"]}'
        )
        return_code = result.return_code or report['test_return_code'] or 0
        return CodexResult(return_code, result.short_summary)
