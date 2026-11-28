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
    report: str = ''


class Codex:
    """Run fresh agent sessions using the configured model."""

    def __init__(self, model: str, log_dir: Path, build_root: Path,
                 dockerfile: str, with_depencity: bool = True, source_root: str = '.') -> None:
        self.build_root = build_root
        self.dockerfile = dockerfile
        self.model = model
        executable = shutil.which('codex')
        self.codex = str(Path(executable).resolve()) if executable else None
        self.log_dir = log_dir
        self.with_depencity = with_depencity
        self.source_root = source_root

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
        result, summary = self._run_codex(work_dir, stdout_log, stderr_log, summary_path, task)
        if result.returncode != 0:
            return CodexResult(result.returncode, '')
        return CodexResult(result.returncode, summary['short_summary'].strip(), summary['report'])

    def _run_codex(self, work_dir: Path, stdout_log: Path, stderr_log: Path,
                   summary_path: Path, task: str):
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
                '--build-root', str(self.build_root),
                '--dockerfile', self.dockerfile,
            ], work_dir, ['docker'],
        ))
        command.extend([
            '--config', 'default_permissions="project"',
            '--config', _filesystem_config(
                work_dir, self.source_root, self.codex, self.log_dir,
            ),
            '--config', 'permissions.project.network.enabled=false',
            '--config', 'approval_policy="never"',
            '--config', 'web_search="disabled"',
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
        with stdout_log.open('w') as stdout, stderr_log.open('w') as stderr:
            result = subprocess.run(command, cwd=work_dir, stdout=stdout, stderr=stderr)
        summary = json.loads(summary_path.read_text()) if result.returncode == 0 else None
        return result, summary


def _filesystem_config(work_dir: Path, source_root: str, codex: str,
                       log_dir: Path) -> str:
    workspace = work_dir.resolve()
    write_root = workspace / source_root
    resolved_write_root = write_root.resolve()
    if not write_root.is_relative_to(workspace) or resolved_write_root != write_root:
        raise ValueError('source_root must resolve directly inside the worker checkout')
    filesystem = {
        ':root': 'deny',
        ':minimal': 'read',
        ':tmpdir': 'deny',
        ':slash_tmp': 'deny',
        codex: 'read',
        str(workspace): 'read',
        str(write_root): 'write',
        str(log_dir.resolve()): 'deny',
    }
    rules = ', '.join(f'{json.dumps(path)} = {json.dumps(access)}'
                      for path, access in filesystem.items())
    return f'permissions.project.filesystem={{ {rules} }}'


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
