"""Exercise evaluated runs against the installed Depencity CLI and real tests."""

import json
import shlex
import subprocess
from threading import Barrier
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


def test_evaluated_iterations_progress_regardless_of_metrics(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    starts = []
    candidates = iter([IMPROVED, WORSE, IMPROVED])

    def run_agent(_self, _name, work_dir, task):
        assert work_dir != repo
        assert 'Target: target.py. Tests: test_target.py.' in task
        starts.append((work_dir / 'target.py').read_text())
        (work_dir / 'target.py').write_text(next(candidates))
        return CodexResult(0, 'simplify the calculation')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, WORSE]
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == IMPROVED
    reports = [json.loads(path.read_text()) for path in sorted(logs.rglob('*.evaluation.json'))]
    assert [report['status'] for report in reports] == ['accepted', 'accepted', 'accepted']
    assert [(report['before']['graph.paths.expressions.count'], report['after']['graph.paths.expressions.count']) for report in reports] == [(2, 1), (1, 3), (3, 1)]
    run_dir, = logs.iterdir()
    assert (run_dir / 'agent-01.2.diff').read_text()
    assert (run_dir / 'agent-01.2.candidate.py').read_text() == WORSE
    assert all('1 passed' in path.read_text() for path in run_dir.glob('*.tests.txt'))
    assert not (repo / '.git').exists()


def test_improvement_filter_rolls_back_and_continues(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    starts = []
    candidates = iter([IMPROVED, WORSE, IMPROVED])

    def run_agent(self, name, work_dir, task):
        starts.append((work_dir / 'target.py').read_text())
        (work_dir / 'target.py').write_text(next(candidates))
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, [*arguments, '--depencity-accept', 'depencity'])
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, IMPROVED]
    reports = [json.loads(p.read_text()) for p in sorted(logs.rglob('*.evaluation.json'))]
    assert [r['status'] for r in reports] == ['accepted', 'rejected', 'rejected']
    assert [r['after']['graph.paths.expressions.count'] for r in reports] == [1, 3, 1]
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == IMPROVED


@pytest.mark.parametrize('after, accepted', [
    ((1, 3), True), ((2, 2), True), ((1, 4), False), ((2, 3), False),
])
def test_improvement_filter_requires_no_metric_regression(tmp_path, monkeypatch, after, accepted):
    from agent_runner.evaluator import Evaluator

    repo, logs, arguments = prepare(tmp_path)
    metrics = ('graph.paths.expressions.count', 'variable.total.write.count')
    measurements = iter([dict(zip(metrics, (2, 3))), dict(zip(metrics, after))])
    monkeypatch.setattr(Evaluator, 'measure', lambda self: next(measurements))

    def run_agent(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, [
        *arguments, '--iterations', '1', '--depencity-accept', 'depencity',
        '--metric', metrics[0], '--metric', metrics[1],
    ])
    assert result.exit_code == 0, result.output
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['accepted'] is accepted
    assert report['after'] == dict(zip(metrics, after))
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == (IMPROVED if accepted else ORIGINAL)


def test_comparison_can_enable_filter_when_continuing(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments[:2] = ['run-experiment']
    arguments.extend(['--iterations', '1'])

    def initial(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', initial)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    root, = logs.iterdir()
    manifest = root / 'run.json'
    calls = []

    def worse(self, name, work_dir, task):
        calls.append(name)
        expected = WORSE if work_dir.name == 'plain' and name != 'plain.2' else IMPROVED
        assert (work_dir / 'target.py').read_text() == expected
        (work_dir / 'target.py').write_text(WORSE)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', worse)
    for total, flags in [
        (2, ['--depencity-accept', 'depencity']), (3, []),
        (4, ['--depencity-accept', 'all']),
    ]:
        result = CliRunner().invoke(main, [
            'run-experiment', '--log-root', str(logs), '--continue',
            '--iterations', str(total), *flags,
        ])
        assert result.exit_code == 0, result.output
        for variant in ('plain', 'depencity'):
            filtered = variant == 'depencity' and total != 4
            report = json.loads((root / variant / f'{variant}.{total}.evaluation.json').read_text())
            assert report['status'] == ('rejected' if filtered else 'accepted')
            assert report['depencity_accept'] == ('depencity' if filtered else 'all')
            assert report['after']['graph.paths.expressions.count'] == 3
            assert (root / variant / 'target.py').read_text() == (IMPROVED if filtered else WORSE)
        assert json.loads(manifest.read_text())['depencity_accept'] == ('all' if total == 4 else 'depencity')
    assert sorted(calls) == ['depencity.2', 'depencity.3', 'depencity.4', 'plain.2', 'plain.3', 'plain.4']


def test_improvement_filter_requires_evaluation(tmp_path):
    result = CliRunner().invoke(main, [
        'run', '--repo', str(tmp_path), '--log-root', str(tmp_path / 'logs'),
        '--depencity-accept', 'depencity',
    ])
    assert result.exit_code == 2
    assert '--depencity-accept requires --depencity-eval' in result.output


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


@pytest.mark.parametrize('after', [(1, 3), (2, 2), (1, 4), (2, 3)])
def test_repeatable_metrics_record_changes_without_filtering(tmp_path, monkeypatch, after):
    from agent_runner.evaluator import Evaluator

    repo, logs, arguments = prepare(tmp_path)
    metrics = ('graph.paths.expressions.count', 'variable.total.write.count')
    measurements = iter([dict(zip(metrics, (2, 3))), dict(zip(metrics, after))])

    def measure(self):
        assert self.metrics == metrics
        return next(measurements)

    def run_agent(_self, _name, work_dir, task):
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
    assert report['accepted'] is True
    assert report['after'] == dict(zip(metrics, after))
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'target.py').read_text() == IMPROVED


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


def test_comparison_runs_variants_in_parallel_and_continues(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments[:2] = ['run-experiment']
    arguments.extend(['--iterations', '1'])
    barrier = Barrier(2)
    calls = []
    prompts = {}

    def run_agent(self, name, work_dir, task):
        variant = work_dir.name
        assert self.with_depencity == (variant == 'depencity')
        prompts[variant] = task
        calls.append((variant, name, (work_dir / 'target.py').read_text()))
        barrier.wait(timeout=15)
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    assert prompts['plain'] == prompts['depencity']
    root, = logs.iterdir()
    saved = {path: path.read_bytes() for path in root.glob('*/*.evaluation.json')}
    assert sorted(calls) == [('depencity', 'depencity.1', ORIGINAL), ('plain', 'plain.1', ORIGINAL)]
    calls.clear()
    result = CliRunner().invoke(main, [
        'run-experiment', '--log-root', str(logs), '--iterations', '2', '--continue',
    ])
    assert result.exit_code == 0, result.output
    assert sorted(calls) == [('depencity', 'depencity.2', IMPROVED), ('plain', 'plain.2', IMPROVED)]
    assert all(path.read_bytes() == data for path, data in saved.items())
    assert (repo / 'target.py').read_text() == ORIGINAL
    for variant in ('plain', 'depencity'):
        assert (root / variant / 'target.py').read_text() == IMPROVED
        report = json.loads((root / variant / f'{variant}.2.evaluation.json').read_text())
        assert report['status'] == 'accepted'


def test_comparison_continue_restores_interrupted_candidate(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments[:2] = ['run-experiment']
    arguments.extend(['--iterations', '1'])
    calls = []

    def interrupted(self, name, work_dir, task):
        calls.append(work_dir.name)
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify')

    monkeypatch.setattr(Codex, 'run', interrupted)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 0, result.output
    root, = logs.iterdir()
    # Simulate interruption after the next agent edited the file but before evaluation.
    (root / 'plain/plain.2.before.py').write_text(IMPROVED)
    (root / 'plain/target.py').write_text('broken candidate!\n')

    def resumed(self, name, work_dir, task):
        assert (work_dir / 'target.py').read_text() == IMPROVED
        calls.append(name)
        return CodexResult(0, 'no change')

    monkeypatch.setattr(Codex, 'run', resumed)
    calls.clear()
    result = CliRunner().invoke(main, [*arguments, '--iterations', '2', '--continue'])
    assert result.exit_code == 0, result.output
    assert sorted(calls) == ['depencity.2', 'plain.2']
    assert (root / 'plain/target.py').read_text() == IMPROVED


def test_comparison_continue_requires_matching_run(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments[:2] = ['run-experiment']
    result = CliRunner().invoke(main, [*arguments, '--continue'])
    assert result.exit_code == 1
    assert 'no comparison to continue' in result.output
    monkeypatch.setattr(Codex, 'run', lambda *args: CodexResult(1, 'failed'))
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1
    result = CliRunner().invoke(main, [*arguments, '--continue', '--model', 'different'])
    assert result.exit_code == 1
    assert 'settings differ' in result.output


def test_comparison_continue_retries_only_failed_variant(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments[:2] = ['run-experiment']
    arguments.extend(['--iterations', '1'])

    def initial(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(1 if work_dir.name == 'plain' else 0, 'candidate')

    monkeypatch.setattr(Codex, 'run', initial)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == 1, result.output
    root, = logs.iterdir()
    depencity_report = root / 'depencity/depencity.1.evaluation.json'
    saved_report = depencity_report.read_bytes()
    calls = []

    def retry(self, name, work_dir, task):
        calls.append(name)
        assert (work_dir / 'target.py').read_text() == ORIGINAL
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify')

    monkeypatch.setattr(Codex, 'run', retry)
    result = CliRunner().invoke(main, ['run-experiment', '--log-root', str(logs), '--continue'])
    assert result.exit_code == 0, result.output
    assert calls == ['plain.1']
    assert depencity_report.read_bytes() == saved_report


@pytest.mark.parametrize('candidate, tamper, accepted', [
    ('value = 4\n', 'replace', False),
    (IMPROVED, 'delete', True),
])
def test_evaluator_uses_original_tests(tmp_path, monkeypatch, candidate, tamper, accepted):
    repo, logs, arguments = prepare(tmp_path)
    arguments.extend(['--iterations', '1'])
    original_tests = (repo / 'test_target.py').read_bytes()

    def run_agent(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(candidate)
        tests = work_dir / 'test_target.py'
        if tamper == 'delete':
            tests.unlink()
        else:
            tests.write_text('def test_always_passes():\n    assert True\n')
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = CliRunner().invoke(main, arguments)
    assert result.exit_code == (0 if accepted else 1), result.output
    workspace, = logs.glob('*/workspace')
    assert (workspace / 'test_target.py').read_bytes() == original_tests
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['accepted'] == accepted
    assert report['test_return_code'] == (0 if accepted else 1)
