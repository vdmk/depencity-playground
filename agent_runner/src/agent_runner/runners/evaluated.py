"""Cumulative refactoring with tests, measurements, and accepted snapshots."""

import click

from agent_runner.codex import CodexResult
from agent_runner.runners.in_place import InPlaceRunner


class EvaluatedRunner(InPlaceRunner):
    """Evaluate each candidate before starting the next iteration."""

    def __init__(self, codex, repo, task, iterations, evaluator):
        super().__init__(codex, repo, task, iterations)
        self.evaluator = evaluator
        target = evaluator.target.relative_to(repo)
        self.task += (
            f' Refactor only {target}; do not edit tests or other files. '
            f'Reduce these module aggregate metrics: {", ".join(evaluator.metrics)}. '
            f'The evaluator runs {evaluator.test_command!r}. Tests must pass; no selected '
            'metric may increase and at least one must decrease. Rejected changes are restored.'
        )

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
