"""Measure file refactorings and retain tested metric improvements."""

import difflib
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_runner.mcp import _docker


@dataclass
class Snapshot:
    source: bytes
    values: dict[str, int | float]


class Evaluator:
    """Evaluate one Python file using Depencity and a pytest script."""

    def __init__(self, repo, target, metrics, test_script):
        self.repo = repo
        self.target = (repo / target).resolve()
        self.metrics = metrics
        self.test_script = test_script

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
                build_root = Path(__file__).resolve().parents[3]
                tests = json.loads(_docker(
                    str(self.test_script), self.repo, build_root,
                    build_root / 'docker/test/Dockerfile',
                    shlex.join(['python', '-m', 'pytest', '-q', str(self.test_script),
                                '-p', 'no:cacheprovider']),
                ))
                Path(f'{log_path}.tests.txt').write_text(tests['output'])
                test_return_code = tests['returncode']
                status = 'tests_failed'
                if test_return_code == 0:
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
