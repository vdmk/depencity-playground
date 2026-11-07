"""Execute a Codex turn and capture its output."""

from pathlib import Path
import subprocess
import shutil


class Codex:
    """Run fresh agent sessions with a shared model and log directory."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.codex = shutil.which('codex')

    def run(
        self,
        log_name: Path,
        work_dir: Path,
        task: str,
    ) -> int:

        if not self.codex:
            raise FileNotFoundError('codex CLI was not found; add it to PATH')

        stdout_log = Path(f'{log_name}.jsonl')
        stderr_log = Path(f'{log_name}.stderr.log')
        command = [
            self.codex,
            'exec',
            '--ephemeral',
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
            f'{log_name}.summary.json',
            '--model',
            self.model,
            task,
        ])
        with stdout_log.open('w') as stdout:
            with stderr_log.open('w') as stderr:
                result = subprocess.run(command, cwd=work_dir, stdout=stdout, stderr=stderr)
        return result.returncode
