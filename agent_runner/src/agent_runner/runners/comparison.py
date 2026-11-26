"""Run isolated plain and Depencity variants concurrently, with restart recovery."""

import json
from pathlib import Path

from agent_runner.codex import Codex
from agent_runner.runners.base import Runner
from agent_runner.runners.evaluated import EvaluatedRunner


VARIANTS = ('plain', 'depencity')


def _restore_finished_iteration(runner, prefix):
    report_path = Path(f'{prefix}.evaluation.json')
    if not report_path.exists():
        return False
    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError:
        report = {}
    if report.get('status') not in ('accepted', 'rejected'):
        return False
    suffix = 'candidate' if report['accepted'] else 'before'
    runner.evaluator.restore_target(Path(f'{prefix}.{suffix}.py').read_bytes())
    return True


class ComparisonRunner(Runner):
    def __init__(self, repo, log_root, task, model, iterations, target, metrics,
                 test_script, resume, reject_if_not_improved, build_root, dockerfile, variants=VARIANTS):
        super().__init__(None, repo, len(variants), task, iterations)
        self.variant_names = tuple(variants)
        self.variants = {}
        for variant in self.variant_names:
            directory = log_root / variant
            directory.mkdir(parents=True, exist_ok=True)
            workspace = directory / 'workspace'
            codex = Codex(model, directory, with_depencity=variant == 'depencity',
                          build_root=build_root, dockerfile=dockerfile)
            self.variants[variant] = EvaluatedRunner(
                codex, repo, task, iterations, target, metrics, test_script,
                workspace=workspace,
                resume=resume and (workspace / target).exists(),
                reject_if_not_improved=reject_if_not_improved in ('all', variant),
            )

    def run_worker(self, name):
        variant = self.variant_names[int(name.rsplit('-', 1)[1]) - 1]
        runner = self.variants[variant]
        for iteration in range(1, self.iterations + 1):
            prefix = runner.codex.log_dir / f'{variant}.{iteration}'
            if _restore_finished_iteration(runner, prefix):
                continue
            if self.stopping:
                break
            checkpoint = Path(f'{prefix}.before.py')
            if checkpoint.exists():
                runner.evaluator.restore_target(checkpoint.read_bytes())
            else:
                checkpoint.write_bytes(runner.evaluator.check_target().read_bytes())
            result = runner.run_iteration(variant, iteration, runner.repo)
            if result.return_code:
                return False
        return True
