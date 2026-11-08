"""Exercise evaluated runs against the installed Depencity CLI and real tests."""

import json
import shlex
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_runner.codex import Codex, CodexResult
from agent_runner.runner import main


ORIGINAL = 'left = 1\nright = 2\nvalue = left + right\n'
IMPROVED = 'value = 3\n'
WORSE = 'left = 1\nright = 2\nfirst = left + right\nvalue = first * left\n'


def prepare(tmp_path):
    repo = tmp_path / 'workspace with spaces'
    repo.mkdir()
    (repo / 'target.py').write_text(ORIGINAL)
    (repo / 'checks.py').write_text(
        'import runpy\n'
        'assert runpy.run_path("target.py")["value"] == 3\n'
        'print("behavior checks passed")\n'
    )
    logs = tmp_path / 'evaluation logs'
    arguments = [
        'run', '--depencity-eval', '--repo', str(repo), '--log-root', str(logs),
        '--target', 'target.py', '--test-command', shlex.join([sys.executable, 'checks.py']),
        '--iterations', '3',
    ]
    return repo, logs, arguments


def test_evaluated_iterations_keep_only_passing_metric_improvements(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    starts = []
    candidates = iter([IMPROVED, WORSE, IMPROVED])

    def run_agent(_self, _name, work_dir, task):
        assert work_dir == repo
        assert 'Refactor only target.py' in task
        assert 'graph.paths.expressions.count' in task
        starts.append((repo / 'target.py').read_text())
        (repo / 'target.py').write_text(next(candidates))
        return CodexResult(0, 'simplify the calculation')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, IMPROVED]
    assert (repo / 'target.py').read_text() == IMPROVED
    reports = [json.loads(path.read_text()) for path in sorted(logs.rglob('*.evaluation.json'))]
    assert [report['status'] for report in reports] == ['accepted', 'rejected', 'rejected']
    assert [(report['before']['graph.paths.expressions.count'], report['after']['graph.paths.expressions.count']) for report in reports] == [(2, 1), (1, 3), (1, 1)]
    run_dir, = logs.iterdir()
    assert (run_dir / 'agent-01.2.diff').read_text()
    assert (run_dir / 'agent-01.2.candidate.py').read_text() == WORSE
    assert (run_dir / 'agent-01.2.source.py').read_text() == IMPROVED
    assert all('behavior checks passed' in path.read_text() for path in run_dir.glob('*.tests.txt'))
    assert not (repo / '.git').exists()


@pytest.mark.parametrize('failure', ['tests', 'syntax', 'agent', 'exception'])
def test_evaluated_failures_restore_target_and_stop(tmp_path, monkeypatch, failure):
    repo, logs, arguments = prepare(tmp_path)
    calls = []

    def run_agent(_self, name, _work_dir, _task):
        calls.append(name)
        (repo / 'target.py').write_text('invalid Python!\n' if failure == 'syntax' else 'value = 4\n')
        if failure == 'exception':
            raise OSError('agent unavailable')
        return CodexResult(7 if failure == 'agent' else 0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1, result.output
    assert calls == ['agent-01.1']
    assert (repo / 'target.py').read_text() == ORIGINAL
    if failure != 'exception':
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

    def run_agent(_self, _name, _work_dir, _task):
        (repo / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify calculation')

    monkeypatch.setattr(Evaluator, 'measure', measure)
    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    assert 'profile unavailable' in result.output
    assert (repo / 'target.py').read_text() == ORIGINAL


@pytest.mark.parametrize('options', [[], ['--target', 'target.py'], ['--test-command', 'pytest']])
def test_evaluation_requires_target_and_tests(tmp_path, options):
    result = CliRunner().invoke(main, [
        'run', '--depencity-eval', '--repo', str(tmp_path), '--log-root', str(tmp_path / 'logs'),
        *options,
    ])
    assert result.exit_code == 2
    assert '--depencity-eval requires --target and --test-command' in result.output
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

    def run_agent(_self, _name, _work_dir, task):
        assert all(metric in task for metric in metrics)
        (repo / 'target.py').write_text(IMPROVED)
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
    assert (repo / 'target.py').read_text() == (IMPROVED if accepted else ORIGINAL)
