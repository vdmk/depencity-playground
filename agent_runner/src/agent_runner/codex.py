"""Execute a Codex turn and capture its output."""

from dataclasses import dataclass
from pathlib import Path
import json
import subprocess
import shutil


@dataclass
class CodexResult:
    return_code: int
    short_summary: str


class Codex:
    """Run fresh agent sessions using the configured model."""

    def __init__(self, model: str, log_dir: Path) -> None:
        self.model = model
        self.codex = shutil.which('codex')
        self.log_dir = log_dir

    def run(
        self,
        iteration_name: str,
        work_dir: Path,
        task: str,
    ) -> CodexResult:
        if not self.codex:
            raise FileNotFoundError('codex CLI was not found; add it to PATH')

        log_path = self.log_dir / f'{iteration_name}'
        stdout_log = Path(f'{log_path}.jsonl')
        stderr_log = Path(f'{log_path}.stderr.log')
        summary_path = Path(f'{log_path}.summary.json')
        command = [
            self.codex,
            'exec',
            '--ephemeral',
            '--skip-git-repo-check',
            '--json',
        ]
        command.extend([
            '--sandbox',
            'workspace-write',
            '--config',
            'approval_policy="on-request"',
            '--cd',
            str(work_dir),
            '--output-schema',
            str(Path(__file__).with_name('codex-output.schema.json')),
            '--output-last-message',
            str(summary_path),
            '--model',
            self.model,
            task,
        ])
        with stdout_log.open('w') as stdout:
            with stderr_log.open('w') as stderr:
                result = subprocess.run(command, cwd=work_dir, stdout=stdout, stderr=stderr)
        if result.returncode != 0:
            return CodexResult(result.returncode, '')
        summary = json.loads(summary_path.read_text())['short_summary'].strip()
        return CodexResult(result.returncode, summary)
