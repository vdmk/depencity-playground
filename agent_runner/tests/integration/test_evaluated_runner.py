"""Exercise evaluated runs against the installed Depencity CLI and real tests."""

import json
import os
import shlex
import subprocess
import tomllib
from threading import Barrier
from pathlib import Path

import pytest

from .cli import invoke_manifest

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
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
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
    arguments = {'mode': 'evaluated', 'repo': str(repo), 'log_root': str(logs), 'target': 'target.py', 'test_script': 'test_target.py', 'iterations': 3}
    return repo, logs, arguments


def test_evaluated_iterations_progress_regardless_of_metrics(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    starts = []
    candidates = iter([IMPROVED, WORSE, IMPROVED])

    def run_agent(_self, _name, work_dir, task):
        assert work_dir != repo
        assert {p.name for p in work_dir.iterdir()} == {'target.py', 'test_target.py'}
        assert 'Target: target.py. Tests: test_target.py.' in task
        starts.append((work_dir / 'target.py').read_text())
        (work_dir / 'target.py').write_text(next(candidates))
        return CodexResult(0, 'simplify the calculation')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, WORSE]
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/depencity/workspace')
    assert (workspace / 'target.py').read_text() == IMPROVED
    reports = [json.loads(path.read_text()) for path in sorted(logs.rglob('*.evaluation.json'))]
    assert [report['status'] for report in reports] == ['accepted', 'accepted', 'accepted']
    assert [(report['before']['graph.paths.expressions.count'], report['after']['graph.paths.expressions.count']) for report in reports] == [(2, 1), (1, 3), (3, 1)]
    run_dir, = logs.iterdir()
    assert (run_dir / 'depencity/agent-01.2.diff').read_text()
    assert (run_dir / 'depencity/agent-01.2.candidate.py').read_text() == WORSE
    assert all('1 passed' in path.read_text() for path in (run_dir / 'depencity').glob('*.tests.txt'))
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
    result = invoke_manifest({**arguments, 'depencity_accept': 'depencity'})
    assert result.exit_code == 0, result.output
    assert starts == [ORIGINAL, IMPROVED, IMPROVED]
    reports = [json.loads(p.read_text()) for p in sorted(logs.rglob('*.evaluation.json'))]
    assert [r['status'] for r in reports] == ['accepted', 'rejected', 'rejected']
    assert [r['after']['graph.paths.expressions.count'] for r in reports] == [1, 3, 1]
    workspace, = logs.glob('*/depencity/workspace')
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
    result = invoke_manifest({**arguments, 'iterations': 1, 'depencity_accept': 'depencity', 'metrics': [metrics[0], metrics[1]]})
    assert result.exit_code == 0, result.output
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['accepted'] is accepted
    assert report['after'] == dict(zip(metrics, after))
    workspace, = logs.glob('*/depencity/workspace')
    assert (workspace / 'target.py').read_text() == (IMPROVED if accepted else ORIGINAL)


def test_comparison_can_enable_filter_when_continuing(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments['variants'] = ['plain', 'depencity']
    arguments.update({'iterations': 1})

    def initial(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', initial)
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    root, = logs.iterdir()
    manifest = root / 'run.toml'
    calls = []

    def worse(self, name, work_dir, task):
        calls.append(name)
        expected = WORSE if work_dir.parent.name == 'plain' and name != 'plain.2' else IMPROVED
        assert (work_dir / 'target.py').read_text() == expected
        (work_dir / 'target.py').write_text(WORSE)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', worse)
    for total, flags in [
        (2, {'depencity_accept': 'depencity'}), (3, {}),
        (4, {'depencity_accept': 'all'}),
    ]:
        result = invoke_manifest({'mode': 'evaluated', 'variants': ['plain', 'depencity'], 'log_root': str(logs), 'resume': True, 'iterations': total, **flags})
        assert result.exit_code == 0, result.output
        for variant in ('plain', 'depencity'):
            filtered = variant == 'depencity' and total != 4
            report = json.loads((root / variant / f'{variant}.{total}.evaluation.json').read_text())
            assert report['status'] == ('rejected' if filtered else 'accepted')
            assert report['depencity_accept'] == ('depencity' if filtered else 'all')
            assert report['after']['graph.paths.expressions.count'] == 3
            assert (root / variant / 'workspace/target.py').read_text() == (IMPROVED if filtered else WORSE)
        assert tomllib.loads(manifest.read_text())['evaluation']['acceptance'] == ('all' if total == 4 else 'depencity')
    assert sorted(calls) == ['depencity.2', 'depencity.3', 'depencity.4', 'plain.2', 'plain.3', 'plain.4']


def test_improvement_filter_requires_evaluation(tmp_path):
    result = invoke_manifest({'mode': 'in-place', 'repo': str(tmp_path), 'log_root': str(tmp_path / 'logs'), 'depencity_accept': 'depencity'})
    assert result.exit_code == 2
    assert 'evaluation is not supported in in-place mode' in result.output


@pytest.mark.parametrize('failure', ['agent', 'exception', 'docker'])
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
    result = invoke_manifest(arguments)
    assert result.exit_code == 1, result.output
    assert calls == ['agent-01.1']
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/depencity/workspace')
    assert (workspace / 'target.py').read_text() == ORIGINAL
    if failure == 'docker':
        assert 'Docker daemon is unavailable' in str(result.exception)
    if failure not in ('exception', 'docker'):
        report, = logs.rglob('*.evaluation.json')
        report = json.loads(report.read_text())
        assert report['accepted'] is False
        assert report['status'] == 'agent_failed'
        assert report['after'] is None


@pytest.mark.parametrize('paired', [False, True])
@pytest.mark.parametrize('bad_source', ['value = 4\n', 'invalid Python!\n'])
def test_failed_tests_roll_back_and_continue(tmp_path, monkeypatch, paired, bad_source):
    repo, logs, arguments = prepare(tmp_path)
    if paired:
        arguments['variants'] = ['plain', 'depencity']
    starts = []

    def run_agent(self, name, work_dir, task):
        iteration = int(name.rsplit('.', 1)[1])
        starts.append((name, (work_dir / 'target.py').read_text()))
        (work_dir / 'target.py').write_text(bad_source if iteration == 1 else IMPROVED)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = invoke_manifest({**arguments, 'iterations': 2})
    assert result.exit_code == 0, result.output
    assert len(starts) == (4 if paired else 2)
    assert all(source == ORIGINAL for _, source in starts)
    reports = [json.loads(p.read_text()) for p in logs.rglob('*.evaluation.json')]
    rejected = [r for r in reports if r['status'] == 'rejected']
    assert len(rejected) == (2 if paired else 1)
    assert all(r['test_return_code'] != 0 and not r['accepted'] for r in rejected)
    assert sum(r['status'] == 'accepted' for r in reports) == (2 if paired else 1)
    if paired:
        starts.clear()
        result = invoke_manifest({'mode': 'evaluated', 'variants': ['plain', 'depencity'], 'log_root': str(logs), 'resume': True, 'iterations': 2})
        assert result.exit_code == 0, result.output
        assert starts == []


def test_single_run_continues_from_saved_checkpoint(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    calls = []

    def initial(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', initial)
    result = invoke_manifest({**arguments, 'iterations': 1, 'task': 'saved task', 'depencity_accept': 'depencity'})
    assert result.exit_code == 0, result.output
    root, = logs.iterdir()
    saved = (root / 'depencity/agent-01.1.evaluation.json').read_bytes()
    # A subsequent interrupted attempt must restart from its checkpoint.
    (root / 'depencity/agent-01.2.before.py').write_text(IMPROVED)
    (root / 'depencity/workspace/target.py').write_text('unfinished source!\n')

    def continued(self, name, work_dir, task):
        calls.append(name)
        assert 'saved task' in task
        assert (work_dir / 'target.py').read_text() == IMPROVED
        (work_dir / 'target.py').write_text('value = 4\n')
        return CodexResult(0, 'failed candidate')

    monkeypatch.setattr(Codex, 'run', continued)
    result = invoke_manifest({'mode': 'evaluated', 'log_root': str(logs), 'resume': True, 'iterations': 3})
    assert result.exit_code == 0, result.output
    assert calls == ['agent-01.2', 'agent-01.3']
    assert (root / 'depencity/agent-01.1.evaluation.json').read_bytes() == saved
    assert (root / 'depencity/workspace/target.py').read_text() == IMPROVED
    calls.clear()
    result = invoke_manifest({'mode': 'evaluated', 'log_root': str(logs), 'resume': True})
    assert result.exit_code == 0, result.output
    assert calls == []
    result = invoke_manifest({'mode': 'evaluated', 'log_root': str(logs), 'resume': True, 'model': 'different-model'})
    assert result.exit_code != 0
    assert 'settings differ' in result.output
    result = invoke_manifest({'mode': 'evaluated', 'log_root': str(logs), 'resume': True, 'iterations': 2})
    assert result.exit_code != 0
    assert 'less than the saved total' in result.output


def test_single_continue_requires_saved_run(tmp_path):
    result = invoke_manifest({'mode': 'in-place', 'log_root': str(tmp_path), 'resume': True})
    assert result.exit_code != 0
    assert 'no run to continue' in result.output


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
    result = invoke_manifest(arguments)
    assert result.exit_code == 1
    assert 'profile unavailable' in result.output
    assert (repo / 'target.py').read_text() == ORIGINAL


@pytest.mark.parametrize('options', [{}, {'target': 'target.py'}, {'test_script': 'test_target.py'}])
def test_evaluation_requires_target_and_tests(tmp_path, options):
    (tmp_path / 'target.py').write_text(ORIGINAL)
    (tmp_path / 'test_target.py').write_text('pass\n')
    result = invoke_manifest({'mode': 'evaluated', 'repo': str(tmp_path), 'log_root': str(tmp_path / 'logs'), **options})
    assert result.exit_code == 2
    assert 'evaluation requires target and test_script' in result.output
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
    arguments.update({'iterations': 1, 'metrics': [metrics[0], metrics[1]]})
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['metrics'] == list(metrics)
    assert report['accepted'] is True
    assert report['after'] == dict(zip(metrics, after))
    assert (repo / 'target.py').read_text() == ORIGINAL
    workspace, = logs.glob('*/depencity/workspace')
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
    result = invoke_manifest({'mode': 'evaluated', 'repo': str(repo), 'log_root': 'results', 'target': 'src/target.py', 'test_script': 'tests/test_target.py'})
    assert result.exit_code == 1, result.output
    assert len(seen) == 1
    assert (repo / 'src/target.py').read_text() == ORIGINAL
    assert (repo / 'unrelated.py').read_text() == 'do_not_copy = True\n'


def test_comparison_runs_variants_in_parallel_and_continues(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments['variants'] = ['plain', 'depencity']
    arguments.update({'iterations': 1})
    barrier = Barrier(2)
    calls = []
    prompts = {}

    def run_agent(self, name, work_dir, task):
        variant = work_dir.parent.name
        assert self.with_depencity == (variant == 'depencity')
        prompts[variant] = task
        calls.append((variant, name, (work_dir / 'target.py').read_text()))
        barrier.wait(timeout=15)
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    assert prompts['plain'] == prompts['depencity']
    root, = logs.iterdir()
    saved = {path: path.read_bytes() for path in root.glob('*/*.evaluation.json')}
    assert sorted(calls) == [('depencity', 'depencity.1', ORIGINAL), ('plain', 'plain.1', ORIGINAL)]
    calls.clear()
    result = invoke_manifest({'mode': 'evaluated', 'variants': ['plain', 'depencity'], 'log_root': str(logs), 'iterations': 2, 'resume': True})
    assert result.exit_code == 0, result.output
    assert sorted(calls) == [('depencity', 'depencity.2', IMPROVED), ('plain', 'plain.2', IMPROVED)]
    assert all(path.read_bytes() == data for path, data in saved.items())
    assert (repo / 'target.py').read_text() == ORIGINAL
    for variant in ('plain', 'depencity'):
        assert (root / variant / 'workspace/target.py').read_text() == IMPROVED
        report = json.loads((root / variant / f'{variant}.2.evaluation.json').read_text())
        assert report['status'] == 'accepted'


def test_comparison_continue_restores_interrupted_candidate(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments['variants'] = ['plain', 'depencity']
    arguments.update({'iterations': 1})
    calls = []

    def interrupted(self, name, work_dir, task):
        calls.append(work_dir.parent.name)
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(0, 'simplify')

    monkeypatch.setattr(Codex, 'run', interrupted)
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    root, = logs.iterdir()
    # Simulate interruption after the next agent edited the file but before evaluation.
    (root / 'plain/plain.2.before.py').write_text(IMPROVED)
    (root / 'plain/workspace/target.py').write_text('broken candidate!\n')

    def resumed(self, name, work_dir, task):
        assert (work_dir / 'target.py').read_text() == IMPROVED
        calls.append(name)
        return CodexResult(0, 'no change')

    monkeypatch.setattr(Codex, 'run', resumed)
    calls.clear()
    result = invoke_manifest({**arguments, 'iterations': 2, 'resume': True})
    assert result.exit_code == 0, result.output
    assert sorted(calls) == ['depencity.2', 'plain.2']
    assert (root / 'plain/workspace/target.py').read_text() == IMPROVED


def test_comparison_continue_requires_matching_run(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments['variants'] = ['plain', 'depencity']
    result = invoke_manifest({**arguments, 'resume': True})
    assert result.exit_code == 1
    assert 'no run to continue' in result.output
    monkeypatch.setattr(Codex, 'run', lambda *args: CodexResult(1, 'failed'))
    result = invoke_manifest(arguments)
    assert result.exit_code == 1
    result = invoke_manifest({**arguments, 'resume': True, 'model': 'different'})
    assert result.exit_code == 1
    assert 'settings differ' in result.output


def test_comparison_continue_retries_only_failed_variant(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)
    arguments['variants'] = ['plain', 'depencity']
    arguments.update({'iterations': 1})

    def initial(self, name, work_dir, task):
        (work_dir / 'target.py').write_text(IMPROVED)
        return CodexResult(1 if work_dir.parent.name == 'plain' else 0, 'candidate')

    monkeypatch.setattr(Codex, 'run', initial)
    result = invoke_manifest(arguments)
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
    result = invoke_manifest({'mode': 'evaluated', 'variants': ['plain', 'depencity'], 'log_root': str(logs), 'resume': True})
    assert result.exit_code == 0, result.output
    assert calls == ['plain.1']
    assert depencity_report.read_bytes() == saved_report


@pytest.mark.parametrize('candidate, tamper, accepted', [
    ('value = 4\n', 'replace', False),
    (IMPROVED, 'delete', True),
])
def test_evaluator_uses_original_tests(tmp_path, monkeypatch, candidate, tamper, accepted):
    repo, logs, arguments = prepare(tmp_path)
    arguments.update({'iterations': 1})
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
    result = invoke_manifest(arguments)
    assert result.exit_code == 0, result.output
    workspace, = logs.glob('*/depencity/workspace')
    assert (workspace / 'test_target.py').read_bytes() == original_tests
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    assert report['accepted'] == accepted
    assert report['test_return_code'] == (0 if accepted else 1)


@pytest.mark.parametrize('filename', ['target.py', 'test_target.py'])
@pytest.mark.parametrize('dangling', [False, True])
def test_evaluation_rejects_worker_symlinks_without_touching_destination(
    tmp_path, monkeypatch, filename, dangling,
):
    repo, logs, arguments = prepare(tmp_path)
    outside = tmp_path / 'outside.py'
    sentinel = b'outside file must remain untouched\n'
    if not dangling:
        outside.write_bytes(sentinel)

    def run_agent(self, name, work_dir, task):
        path = work_dir / filename
        path.unlink()
        path.symlink_to(outside)
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = invoke_manifest(arguments)
    assert result.exit_code == 1
    assert 'symlinks are not allowed' in result.output
    assert outside.exists() is not dangling
    if not dangling:
        assert outside.read_bytes() == sentinel


def test_workspace_path_rejects_symlinked_parent(tmp_path):
    from agent_runner.evaluator import checked_workspace_path

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'test_target.py').write_text('original\n')
    (workspace / 'tests').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError, match='symlinks are not allowed'):
        checked_workspace_path(workspace, 'tests/test_target.py').write_text('replacement\n')
    assert (outside / 'test_target.py').read_text() == 'original\n'


def test_plain_only_variant_disables_tools_and_metric_gate(tmp_path, monkeypatch):
    repo, logs, arguments = prepare(tmp_path)

    def run_agent(self, name, work_dir, task):
        assert self.with_depencity is False
        (work_dir / 'target.py').write_text(WORSE)
        return CodexResult(0, 'passing candidate with more expression paths')

    monkeypatch.setattr(Codex, 'run', run_agent)
    result = invoke_manifest({**arguments, 'iterations': 1, 'variants': ['plain'],
                              'depencity_accept': 'depencity'})
    assert result.exit_code == 0, result.output
    run_dir = next(logs.iterdir())
    record = tomllib.loads((run_dir / 'run.toml').read_text())
    assert record['variants'] == ['plain']
    report = json.loads((run_dir / 'plain/agent-01.1.evaluation.json').read_text())
    assert report['accepted'] is True
    assert (run_dir / 'plain/workspace/target.py').read_text() == WORSE


def test_evaluation_measures_root_aggregate(tmp_path, monkeypatch):
    fixtures = Path(__file__).resolve().parents[3] / 'experiments/fixtures'
    for name in ('calculator.py', 'test_calculator.py'):
        (tmp_path / name).write_bytes((fixtures / name).read_bytes())

    def run_agent(self, name, work_dir, task):
        return CodexResult(0, 'preserve calculator for scope measurement')

    monkeypatch.setattr(Codex, 'run', run_agent)
    logs = tmp_path / 'logs'
    result = invoke_manifest(dict(mode='evaluated', repo=str(tmp_path), log_root=str(logs),
                                  target='calculator.py', test_script='test_calculator.py'))
    assert result.exit_code == 0, result.output
    report_path, = logs.rglob('*.evaluation.json')
    report = json.loads(report_path.read_text())
    # This fixture's module aggregate is 16,333; the full root includes more paths.
    assert report['before'] == {'graph.paths.expressions.count': 20926}
    assert report['after'] == report['before']
