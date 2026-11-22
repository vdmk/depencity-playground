"""Measure file refactorings and retain changes that pass tests."""

import difflib
import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_runner.mcp import _docker


def checked_workspace_path(root, relative):
    """Reject symlinks and non-regular files before host-side file access."""
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise OSError(f'path must be relative to workspace: {relative}')
    path = root / relative
    # Resolving must not change any component below the workspace root.
    if root.is_symlink() or path.resolve() != root.resolve() / relative:
        raise OSError(f'workspace symlinks are not allowed: {path}')
    if path.exists() and not path.is_file():
        raise OSError(f'workspace file must be regular: {path}')
    return path


@dataclass
class Snapshot:
    source: bytes
    values: dict


class Evaluator:
    """Evaluate one Python file using Depencity and a pytest script."""

    def __init__(self, repo, target, metrics, test_script, reject_if_not_improved,
                 build_root, dockerfile):
        self.build_root = build_root
        self.dockerfile = build_root / dockerfile
        self.repo = repo
        self.target = checked_workspace_path(repo, target)
        self.metrics = metrics
        self.test_script = test_script
        self.test_source = checked_workspace_path(repo, test_script).read_bytes()
        self.reject_if_not_improved = reject_if_not_improved

    def measure(self):
        self.check_target()
        executable = shutil.which('depencity')
        result = subprocess.run(
            [executable, 'profile', '--format', 'json', '--depth', '0', str(self.target)],
            cwd=self.repo, capture_output=True, text=True, check=True,
        )
        for scope in json.loads(result.stdout)['scopes']:
            if scope['id'] == '__root__':
                return scope['profile']
        raise ValueError(f'no root profile for {self.target}')

    def snapshot(self):
        return Snapshot(self.check_target().read_bytes(), self.measure())

    def check_target(self):
        return checked_workspace_path(self.repo, self.target.relative_to(self.repo))

    def restore_target(self, source):
        self.check_target().write_bytes(source)

    def restore_tests(self):
        checked_workspace_path(self.repo, self.test_script).write_bytes(self.test_source)

    def evaluate(self, before, log_path, agent_return_code):
        accepted = False
        try:
            self.restore_tests()
            self.check_target()
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
                tests = json.loads(_docker(
                    str(self.test_script), self.repo, self.build_root, self.dockerfile,
                    shlex.join(['python', '-m', 'pytest', '-q', str(self.test_script),
                                '-p', 'no:cacheprovider']),
                ))
                Path(f'{log_path}.tests.txt').write_text(tests['output'])
                test_return_code = tests['returncode']
                status = 'rejected'
                if test_return_code == 0:
                    after_values = self.measure()
                    Path(f'{log_path}.profile.json').write_text(
                        json.dumps(after_values, indent=2) + '\n'
                    )
                    accepted = not self.reject_if_not_improved or (
                        all(after_values[key] <= before.values[key] for key in self.metrics)
                        and any(after_values[key] < before.values[key] for key in self.metrics)
                    )
                    status = 'accepted' if accepted else 'rejected'
            report = {
                'target': str(self.target), 'metrics': self.metrics,
                'before': {key: before.values[key] for key in self.metrics},
                'after': ({key: after_values[key] for key in self.metrics}
                          if after_values is not None else None),
                'accepted': accepted,
                'status': status, 'agent_return_code': agent_return_code,
                'test_return_code': test_return_code,
                'reject_if_not_improved': self.reject_if_not_improved,
            }
            pending = Path(f'{log_path}.evaluation.json.tmp')
            pending.write_text(json.dumps(report, indent=2) + '\n')
            pending.replace(Path(f'{log_path}.evaluation.json'))
            return report
        finally:
            if not accepted:
                self.restore_target(before.source)
