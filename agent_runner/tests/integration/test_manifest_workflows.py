"""Exercise manifest-driven execution, checkpoint records, and HTML reports."""

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_runner.codex import Codex, CodexResult
from agent_runner.runner import main


PROJECT = Path(__file__).resolve().parents[3]


def test_manifest_runs_from_another_directory_and_snapshots_prompt(tmp_path, monkeypatch):
    definition = tmp_path / 'definitions'
    definition.mkdir()
    repo = tmp_path / 'project with spaces'
    repo.mkdir()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    task = 'Simplify the "parser".\nKeep Unicode: λ.\n'
    (definition / 'task.md').write_text(task)
    manifest = definition / 'experiment.toml'
    manifest.write_text(
        'name = "parser-search"\n'
        'repo = "../project with spaces"\n'
        'log_root = "../runs"\n'
        'task_file = "task.md"\n'
        '[agent]\nmodel = "test-model"\n'
        'iterations = 1\n'
    )
    calls = []

    def run_agent(self, name, work_dir, prompt):
        calls.append(name)
        assert work_dir == repo
        assert prompt.startswith(task)
        assert self.model == 'test-model'
        (self.log_dir / f'{name}.summary.json').write_text('{"short_summary":"candidate"}')
        return CodexResult(0, 'candidate')

    monkeypatch.setattr(Codex, 'run', run_agent)
    monkeypatch.chdir(elsewhere)
    result = CliRunner().invoke(main, ['run', str(manifest)])
    assert result.exit_code == 0, result.output
    run_dir, = (tmp_path / 'runs').iterdir()
    saved = run_dir / 'run.toml'
    record = tomllib.loads(saved.read_text())
    assert record['task'] == task
    assert record['repo'] == str(repo)
    assert record['log_root'] == str(tmp_path / 'runs')
    assert record['agent']['model'] == 'test-model'
    assert record['agent']['iterations'] == 1
    # The saved definition stays usable without its original task file.
    (definition / 'task.md').unlink()
    saved.write_text(saved.read_text().replace('iterations = 1', 'iterations = 2'))
    result = CliRunner().invoke(main, ['run', str(saved), '--continue'])
    assert result.exit_code == 0, result.output
    assert calls == ['agent-01.1', 'agent-01.2']
    # A changed source prompt must not silently change a continuing experiment.
    (definition / 'task.md').write_text('Different task')
    result = CliRunner().invoke(main, ['run', str(manifest), '--continue'])
    assert result.exit_code != 0
    assert calls == ['agent-01.1', 'agent-01.2']


@pytest.mark.parametrize('body, message', [
    ('log_rooot = "runs"', 'unknown manifest keys'),
    ('log_root = "runs"\n[agent]\niteration = 2', 'unknown agent keys'),
    ('log_root = "runs"\n[agent]\niterations = true', 'agent.iterations must be an integer'),
    ('log_root = "runs"\n[agent]\nmodel = 3', 'agent.model must be a nonempty string'),
    ('log_root = "runs"\n[agent]\nworkers = 2', 'requires workspaces mode'),
    ('log_root = "runs"\nbranch_mode = "fresh"', 'branch_mode requires workspaces mode'),
    ('log_root = "runs"\nmode = "workspaces"\nbranch_mode = "invalid"',
     'branch_mode must be fresh or incremental'),
    ('log_root = "runs"\ntask = "inline"\ntask_file = "task.md"', 'use task or task_file'),
    ('log_root = "runs"\n[agent]\ntools = ["profile"]', 'unknown agent keys'),
    ('log_root = "runs"\nmode = "evaluated"\n[evaluation]\n'
     'target = "../outside.py"\ntest_script = "test_target.py"', 'must be inside repo'),
    ('log_root = "runs"\nmode = "evaluated"\n[evaluation]\n'
     'target = "target.py"\ntest_script = "test_target.py"\nmetrics = []', 'nonempty array'),
])
def test_invalid_manifests_fail_before_execution(tmp_path, monkeypatch, body, message):
    (tmp_path / 'target.py').write_text('value = 1\n')
    (tmp_path / 'test_target.py').write_text('pass\n')
    manifest = tmp_path / 'experiment.toml'
    manifest.write_text(body + '\n')

    def unexpected(*args):
        pytest.fail('invalid experiments must not launch an agent')

    monkeypatch.setattr(Codex, 'run', unexpected)
    result = CliRunner().invoke(main, ['run', str(manifest)])
    assert result.exit_code == 2, result.output
    assert message in result.output
    assert not (tmp_path / 'runs').exists()


@pytest.mark.parametrize('paired', [False, True])
def test_report_reads_toml_and_evaluation_layouts(tmp_path, paired):
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    (run_dir / 'run.toml').write_text(
        'name = "report-example"\n'
        f'mode = "{"comparison" if paired else "evaluated"}"\n'
        'task = "Simplify <parser>"\n'
        '[agent]\nmodel = "test-model"\n'
        'iterations = 1\n'
        '[evaluation]\ntarget = "target.py"\ntest_script = "test_target.py"\n'
        'metrics = ["graph.paths.expressions.count"]\nacceptance = "depencity"\n'
    )
    for variant in (('plain', 'depencity') if paired else ('agent-01',)):
        directory = run_dir / variant if paired else run_dir
        directory.mkdir(exist_ok=True)
        report = dict(metrics=['graph.paths.expressions.count'],
                      before={'graph.paths.expressions.count': 10},
                      after={'graph.paths.expressions.count': 5},
                      status='accepted', accepted=True, test_return_code=0)
        (directory / f'{variant}.1.evaluation.json').write_text(json.dumps(report))
    output = tmp_path / 'published' / 'report.html'
    result = subprocess.run(
        [sys.executable, str(PROJECT / 'scripts/experiment_report.py'), str(run_dir),
         '--output', str(output)], text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    html = output.read_text()
    assert 'report-example' in html
    assert 'test-model' in html
    assert 'graph.paths.expressions.count' in html
    assert 'Simplify \\u003cparser>' in html
    assert all(variant in html for variant in (('plain', 'depencity') if paired else ('agent-01',)))


@pytest.mark.parametrize(('experiment', 'name'), [
    ('path-expressions/simple', 'path-expressions'),
    ('path-expressions/internal-20', 'path-expressions-internal-20'),
    ('path-expressions/strict-target-10', 'path-expressions-strict-target-10'),
])
def test_catalog_manifests_load_from_other_working_directory(tmp_path, monkeypatch, experiment, name):
    from agent_runner.manifest import load_manifest

    monkeypatch.chdir(tmp_path)
    settings = load_manifest(PROJECT / 'experiments' / experiment / 'experiment.toml')
    assert settings['name'] == name
    assert Path(settings['repo']) == PROJECT / 'experiments/fixtures'
    assert Path(settings['log_root']) == PROJECT / 'out/experiments' / name
    assert settings['task'] == (PROJECT / 'experiments' / experiment / 'task.md').read_text()
