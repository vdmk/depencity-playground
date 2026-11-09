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

    def __init__(self, model: str, log_dir: Path, with_depencity: bool = True) -> None:
        self.model = model
        self.codex = shutil.which('codex')
        self.log_dir = log_dir
        self.with_depencity = with_depencity

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
            '--ignore-user-config',
        ]
        project = Path(__file__).resolve().parents[3]
        if self.with_depencity:
            command.extend(_create_mcp_server_options(
                'depencity', [
                    'run', '--project', str(project), 'depencity-mcp',
                    '--workspace', str(work_dir),
                ], work_dir, ['profile'],
            ))
        command.extend(_create_mcp_server_options(
            'agent-runner', [
                'run', '--project', str(project), 'agent-runner-mcp',
                '--workspace', str(work_dir),
                '--build-root', str(project),
                '--dockerfile', 'docker/test/Dockerfile',
            ], work_dir, ['docker'],
        ))
        filesystem = {
            ':root': 'deny',
            ':minimal': 'read',
            ':tmpdir': 'deny',
            ':slash_tmp': 'deny',
            str(work_dir.resolve()): 'write',
            str(self.log_dir.resolve()): 'deny',
        }
        command.extend(['--config', 'default_permissions="project"'])
        for path, access in filesystem.items():
            command.extend(['--config',
                            f'permissions.project.filesystem.{json.dumps(path)}={json.dumps(access)}'])
        command.extend(['--config', 'permissions.project.network.enabled=false',
                        '--config', 'approval_policy="never"',
                        '--config', 'web_search="disabled"'])
        command.extend([
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


def _create_mcp_server_options(
    name: str,
    arguments: list[str],
    worktree: Path,
    enabled_tools: list[str] | None = None,
) -> list[str]:
    server = f'mcp_servers.{name}'
    options = [
        '--config',
        f'{server}.command="uv"',
        '--config',
        f'{server}.args=' + json.dumps(arguments),
        '--config',
        f'{server}.cwd={json.dumps(str(worktree))}',
        '--config',
        f'{server}.default_tools_approval_mode="approve"',
    ]
    if enabled_tools is not None:
        options.extend([
            '--config',
            f'{server}.enabled_tools=' + json.dumps(enabled_tools),
        ])
    return options
