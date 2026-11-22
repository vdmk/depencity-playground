"""Cumulative refactoring with tests, measurements, and accepted snapshots."""

import shutil
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import click

from agent_runner.evaluator import Evaluator, checked_workspace_path
from agent_runner.runners.in_place import InPlaceRunner


class EvaluatedRunner(InPlaceRunner):
    """Evaluate each candidate before starting the next iteration."""

    def __init__(self, codex, repo, task, iterations, target, metrics, test_script,
                 workspace, resume, reject_if_not_improved):
        target = (repo / target).resolve().relative_to(repo)
        test_script = (repo / test_script).resolve().relative_to(repo)
        for relative_path in (target, test_script):
            if not resume or relative_path == test_script:
                destination = checked_workspace_path(workspace, relative_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / relative_path, destination)
        super().__init__(codex, workspace, task, iterations, resume=resume)
        self.evaluator = Evaluator(
            workspace, target, metrics, test_script,
            reject_if_not_improved=reject_if_not_improved,
            build_root=codex.build_root, dockerfile=codex.dockerfile,
        )
        self.task += f' Target: {target}. Tests: {test_script}.'

    def run_worker(self, name):
        for iteration in range(1, self.iterations + 1):
            prefix = self.codex.log_dir / f'{name}.{iteration}'
            report_path = Path(f'{prefix}.evaluation.json')
            if self.resume and report_path.exists():
                report = json.loads(report_path.read_text())
                if report.get('status') in ('accepted', 'rejected'):
                    suffix = 'candidate' if report['accepted'] else 'before'
                    self.evaluator.restore_target(Path(f'{prefix}.{suffix}.py').read_bytes())
                    continue
            if self.stopping:
                break
            checkpoint = Path(f'{prefix}.before.py')
            if self.resume and checkpoint.exists():
                self.evaluator.restore_target(checkpoint.read_bytes())
            result = self.run_iteration(name, iteration, self.repo)
            if result.return_code:
                return False
        return True

    def run_iteration(self, name, iteration, work_dir):
        self.evaluator.restore_tests()
        before = self.evaluator.snapshot()
        (self.codex.log_dir / f'{name}.{iteration}.before.py').write_bytes(before.source)
        try:
            target = self.evaluator.target.relative_to(work_dir)
            with TemporaryDirectory() as directory:
                turn = Path(directory).resolve()
                for relative in (target, self.evaluator.test_script):
                    destination = turn / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(work_dir / relative, destination)
                result = super().run_iteration(name, iteration, turn)
                candidate = checked_workspace_path(turn, target)
                if candidate.exists():
                    shutil.copyfile(candidate, self.evaluator.check_target())
                else:
                    self.evaluator.check_target().unlink()

            report = self.evaluator.evaluate(
                before, self.codex.log_dir / f'{name}.{iteration}', result.return_code,
            )
        except BaseException:
            self.evaluator.restore_target(before.source)
            raise
        click.echo(
            f'{name}.{iteration}: {report["status"]}; '
            f'{report["metrics"]}: {report["before"]} -> {report["after"]}'
        )
        return result
