"""Exercise evaluated runs against the installed Depencity CLI and real tests."""

import json
import shlex
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_runner.codex import Codex, CodexResult
from agent_runner.runner import main


ORIGINAL = 'left = 1\nright = 2\nvalue = left + right\n'
IMPROVED = 'value = 3\n'
WORSE = 'left = 1\nright = 2\nfirst = left + right\nvalue = first * left\n'


@pytest.fixture(autouse=True)
def docker_backend(monkeypatch):
    # The suite already runs inside Docker; replace nested Docker at its boundary.
    def run_tests(path, workspace_root, build_root, dockerfile, command):
        assert (workspace_root / path).is_file()
        assert dockerfile == build_root / 'docker/test/Dockerfile'
        result = subprocess.run(
            shlex.split(command), cwd=workspace_root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        return json.dumps({'returncode': result.returncode, 'output': result.stdout})

    monkeypatch.setattr('agent_runner.evaluator._docker', run_tests)


def prepare(tmp_path):
    repo = tmp_path / 'workspace with spaces'
    repo.mkdir()
    (repo / 'target.py').write_text(ORIGINAL)
    (repo / 'test_target.py').write_text(
        'import runpy\n'
        'def test_behavior():\n'
        '    assert runpy.run_path("target.py")["value"] == 3\n'
    )
    logs = tmp_path / 'evaluation logs'
    arguments = [
        'run', '--depencity-eval', '--repo', str(repo), '--log-root', str(logs),
        '--target', 'target.py', '--test-script', 'test_target.py',
        '--iterations', '3',
    ]
    return repo, logs, arguments


def test_evaluated_iterations_keep_only_passing_metric_improvements(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    starts = []
    candidates = iter([IMPROVED, WORSE, IMPROVED])

    def run_agent(_self, _name, work_dir, task):
        assert work_dir != repo
        assert 'Refactor only target.py' in task
        assert 'graph.paths.expressions.count' in task
        starts.append((work_dir / 'target.py').read_text())
        (work_dir / 'target.py').write_text(next(candidates))
        return CodexResult(0, 'simplify the calculation')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, IMPROVED]
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == IMPROVED
    reports = [json.loads(path.read_text()) for path in sorted(logs.rglob('*.evaluation.json'))]
    assert [report['status'] for report in reports] == ['accepted', 'rejected', 'rejected']
    assert [(report['before']['graph.paths.expressions.count'], report['after']['graph.paths.expressions.count']) for report in reports] == [(2, 1), (1, 3), (1, 1)]
    run_dir, = logs.iterdir()
    assert (run_dir / 'agent-01.2.diff').read_text()
    assert (run_dir / 'agent-01.2.candidate.py').read_text() == WORSE
    assert (run_dir / 'agent-01.2.source.py').read_text() == IMPROVED
    assert all('1 passed' in path.read_text() for path in run_dir.glob('*.tests.txt'))
    assert not (repo / '.git').exists()


@pytest.mark.parametrize('failure', ['tests', 'syntax', 'agent', 'exception', 'docker'])
def test_evaluated_failures_restore_target_and_stop(tmp_path, monkeypatch, failure):
    repo, logs, arguments = prepare(tmp_path)
    calls = []

    def run_agent(_self, name, work_dir, _task):
        calls.append(name)
        (work_dir / 'target.py').write_text('invalid Python!\n' if failure == 'syntax' else 'value = 4\n')
        if failure == 'exception':
            raise OSError('agent unavailable')
        return CodexResult(7 if failure == 'agent' else 0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    if failure == 'docker':
        def unavailable(*args):
            raise RuntimeError('Docker daemon is unavailable')
        monkeypatch.setattr('agent_runner.evaluator._docker', unavailable)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1, result.output
    assert calls == ['agent-01.1']
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == ORIGINAL
    if failure == 'docker':
        assert 'Docker daemon is unavailable' in str(result.exception)
    if failure not in ('exception', 'docker'):
        report, = logs.rglob('*.evaluation.json')
        report = json.loads(report.read_text())
        assert report['accepted'] is False
        assert report['status'] == ('agent_failed' if failure == 'agent' else 'tests_failed')
        assert report['after'] is None


def test_evaluation_error_restores_candidate(tmp_path, monkeypatch):
    from agent_runner.evaluator import Evaluator

    repo, _logs, arguments = prepare(tmp_path)
    measurements = iter([{'graph.paths.expressions.count': 2}, OSError('profile unavailable')])

    def measure(_self):
        measurement = next(measurements)
        if isinstance(measurement, Exception):
            raise measurement
        return measurement

    def run_agent(_self, _name, work_dir, _task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify calculation')

    monkeypatch.setattr(Evaluator, 'measure', measure)
    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    assert 'profile unavailable' in result.output
    assert (repo / 'target.py').read_text() == ORIGINAL


@pytest.mark.parametrize('options', [[], ['--target', 'target.py'], ['--test-script', 'test_target.py']])
def test_evaluation_requires_target_and_tests(tmp_path, options):
    result = CliRunner().invoke(main, [
        'run', '--depencity-eval', '--repo', str(tmp_path), '--log-root', str(tmp_path / 'logs'),
        *options,
    ])
    assert result.exit_code == 2
    assert '--depencity-eval requires --target and --test-script' in result.output
    assert not (tmp_path / 'logs').exists()


@pytest.mark.parametrize('after, accepted', [
    ((1, 3), True),
    ((2, 2), True),
    ((1, 4), False),
    ((2, 3), False),
])
def test_repeatable_metrics_require_improvement_without_regression(tmp_path, monkeypatch, after, accepted):
    from agent_runner.evaluator import Evaluator

    repo, logs, arguments = prepare(tmp_path)
    metrics = ('graph.paths.expressions.count', 'variable.total.write.count')
    measurements = iter([dict(zip(metrics, (2, 3))), dict(zip(metrics, after))])

    def measure(self):
        assert self.metrics == metrics
        return next(measurements)

    def run_agent(_self, _name, work_dir, task):
        assert all(metric in task for metric in metrics)
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify calculation')

    monkeypatch.setattr(Evaluator, 'measure', measure)
    monkeypatch.setattr(Codex, 'run', run_agent)
    arguments.extend(['--iterations', '1', '--metric', metrics[0], '--metric', metrics[1]])
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['metrics'] == list(metrics)
    assert report['accepted'] == accepted
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == (IMPROVED if accepted else ORIGINAL)


def test_evaluated_runner_copies_only_target_and_test_script(tmp_path, monkeypatch):
    repo = tmp_path / 'project'
    (repo / 'src').mkdir(parents=True)
    (repo / 'tests').mkdir()
    (repo / 'src/target.py').write_text(ORIGINAL)
    (repo / 'tests/test_target.py').write_text('def test_value():\n    assert True\n')
    (repo / 'unrelated.py').write_text('do_not_copy = True\n')
    seen = []

    def run_agent(self, _name, work_dir, _task):
        seen.append(work_dir)
        assert work_dir == self.log_dir / 'workspace'
        copied = {path.relative_to(work_dir).as_posix() for path in work_dir.rglob('*.py')}
        assert copied == {'src/target.py', 'tests/test_target.py'}
        assert (work_dir / 'tests/test_target.py').read_bytes() == (repo / 'tests/test_target.py').read_bytes()
        return CodexResult(1, '')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, [
        'run', '--depencity-eval', '--repo', str(repo), '--log-root', 'results',
        '--target', 'src/target.py', '--test-script', 'tests/test_target.py',
    ])
    assert result.exit_code == 1, result.output
    assert len(seen) == 1
    assert (repo / 'src/target.py').read_text() == ORIGINAL
    assert (repo / 'unrelated.py').read_text() == 'do_not_copy = True\n'
