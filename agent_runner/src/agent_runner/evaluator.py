"""Measure file refactorings and retain tested metric improvements."""

import difflib
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Snapshot:
    source: bytes
    values: dict[str, int | float]


class Evaluator:
    """Evaluate one Python file using Depencity and a caller-supplied test command."""

    def __init__(self, repo, target, metrics, test_command):
        self.repo = repo
        self.target = (repo / target).resolve()
        self.metrics = metrics
        self.test_command = test_command

    def measure(self):
        executable = shutil.which('depencity')
        result = subprocess.run(
            [executable, 'profile', '--format', 'json', '--depth', '1', str(self.target)],
            cwd=self.repo, capture_output=True, text=True, check=True,
        )
        pending = json.loads(result.stdout)['scopes']
        while pending:
            scope = pending.pop()
            if scope['id'] == '__module__':
                return {metric: scope['profile'][metric] for metric in self.metrics}
            pending.extend(scope.get('children', []))
        raise ValueError(f'no module profile for {self.target}')

    def snapshot(self):
        return Snapshot(self.target.read_bytes(), self.measure())

    def evaluate(self, before, log_path, agent_return_code):
        accepted = False
        try:
            candidate = self.target.read_bytes() if self.target.exists() else b''
            Path(f'{log_path}.before.py').write_bytes(before.source)
            Path(f'{log_path}.candidate.py').write_bytes(candidate)
            Path(f'{log_path}.diff').write_text(''.join(difflib.unified_diff(
                before.source.decode().splitlines(keepends=True),
                candidate.decode().splitlines(keepends=True),
                fromfile=f'before/{self.target.name}', tofile=f'candidate/{self.target.name}',
            )))
            after_values = None
            test_return_code = None
            status = 'agent_failed'
            if agent_return_code == 0:
                tests = subprocess.run(
                    shlex.split(self.test_command), cwd=self.repo,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                Path(f'{log_path}.tests.txt').write_text(tests.stdout)
                test_return_code = tests.returncode
                status = 'tests_failed'
                if tests.returncode == 0:
                    after_values = self.measure()
                    accepted = (
                        all(after_values[metric] <= before.values[metric] for metric in self.metrics)
                        and any(after_values[metric] < before.values[metric] for metric in self.metrics)
                    )
                    status = 'accepted' if accepted else 'rejected'
            report = {
                'target': str(self.target), 'metrics': self.metrics,
                'before': before.values, 'after': after_values, 'accepted': accepted,
                'status': status, 'agent_return_code': agent_return_code,
                'test_return_code': test_return_code,
            }
            Path(f'{log_path}.evaluation.json').write_text(json.dumps(report, indent=2) + '\n')
            return report
        finally:
            if not accepted:
                self.target.write_bytes(before.source)
            Path(f'{log_path}.source.py').write_bytes(self.target.read_bytes())
