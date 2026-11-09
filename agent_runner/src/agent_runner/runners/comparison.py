"""Run isolated plain and Depencity variants concurrently, with restart recovery."""

import json
from pathlib import Path

from agent_runner.codex import Codex
from agent_runner.runners.base import Runner
from agent_runner.runners.evaluated import EvaluatedRunner


VARIANTS = ('plain', 'depencity')


class ComparisonRunner(Runner):
    def __init__(self, repo, log_root, task, model, iterations, target, metrics,
                 test_script, resume, accept_improvements_only):
        super().__init__(None, repo, len(VARIANTS), task, iterations)
        self.variants = {}
        for variant in VARIANTS:
            directory = log_root / variant
            directory.mkdir(parents=True, exist_ok=True)
            codex = Codex(model, directory, with_depencity=variant == 'depencity')
            self.variants[variant] = EvaluatedRunner(
                codex, repo, task, iterations, target, metrics, test_script,
                workspace=directory, resume=resume and (directory / target).exists(),
                accept_improvements_only=accept_improvements_only,
            )

    def run_worker(self, name):
        variant = VARIANTS[int(name.rsplit('-', 1)[1]) - 1]
        runner = self.variants[variant]
        target = runner.evaluator.target
        for iteration in range(1, self.iterations + 1):
            prefix = runner.codex.log_dir / f'{variant}.{iteration}'
            report_path = Path(f'{prefix}.evaluation.json')
            if report_path.exists():
                try:
                    report = json.loads(report_path.read_text())
                except json.JSONDecodeError:
                    report = {}
                if report.get('status') in ('accepted', 'rejected'):
                    suffix = 'candidate' if report['accepted'] else 'before'
                    target.write_bytes(Path(f'{prefix}.{suffix}.py').read_bytes())
                    continue
            if self.stopping:
                break
            checkpoint = Path(f'{prefix}.before.py')
            if checkpoint.exists():
                target.write_bytes(checkpoint.read_bytes())
            else:
                checkpoint.write_bytes(target.read_bytes())
            result = runner.run_iteration(variant, iteration, runner.repo)
            if result.return_code:
                return False
        return True
