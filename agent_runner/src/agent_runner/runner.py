"""Run Codex iterations, optionally in isolated Git worktrees."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import click

from agent_runner.cli_utils import cli_errors
from agent_runner.codex import Codex
from agent_runner.runners.evaluated import EvaluatedRunner
from agent_runner.runners.comparison import ComparisonRunner
from agent_runner.runners.fresh import FreshRunner
from agent_runner.runners.incremental import IncrementalRunner
from agent_runner.runners.in_place import InPlaceRunner


DEFAULT_TASK = (
    'Make one coherent, behavior-preserving refactoring. Follow repository '
    'guidance and run relevant tests.'
)


@click.group()
def main() -> None:
    """Run independent candidates or cumulative refactoring iterations."""


def _common_options(command):
    for option in reversed([
        click.option('--log-root', type=click.Path(path_type=Path),
                     required=True, help='Base log directory, relative to --repo or absolute.'),
        click.option('--repo', type=click.Path(path_type=Path), default=Path.cwd),
        click.option('--task', default=DEFAULT_TASK, help='Task for each fresh agent session.'),
        click.option('--model', default='gpt-6-luna', show_default=True),
    ]):
        command = option(command)
    return command

@main.command()
@click.option('--iterations', type=click.IntRange(1, 1000), default=1, show_default=True)
@click.option('--continue', 'resume', is_flag=True, help='Continue the latest single-worker run in --log-root.')
@click.option('--depencity-eval', is_flag=True, help='Measure Depencity metrics and validate changes with Docker tests.')
@click.option('--depencity-accept', type=click.Choice(['all', 'depencity']),
              default='all', show_default=True,
              help='Accept passing tests, or also require metric improvement with depencity.')
@click.option('--target', type=click.Path(path_type=Path), help='Python file to evaluate, relative to --repo.')
@click.option('--metric', 'metrics', multiple=True,
              default=('graph.paths.expressions.count',), show_default=True,
              help='Metric to record; repeat to select several.')
@click.option('--test-script', type=click.Path(path_type=Path), help='Pytest file to copy and run, relative to --repo.')
@_common_options
@cli_errors
def run(repo, task, model, iterations, log_root, depencity_eval, target, metrics, test_script,
        depencity_accept, resume) -> None:
    """Run cumulative iterations in the supplied directory without Git commits."""
    repo = repo.resolve()
    settings = dict(repo=str(repo), task=task, model=model, iterations=iterations,
                    depencity_eval=depencity_eval, target=str(target) if target else None,
                    metrics=list(metrics), test_script=str(test_script) if test_script else None,
                    depencity_accept=depencity_accept)
    for key in ('target', 'test_script'):
        if settings[key] is not None:
            settings[key] = str((repo / settings[key]).resolve().relative_to(repo))
    if resume:
        base = (repo / log_root).resolve()
        manifests = sorted(base.glob('*/run.json'))
        manifests = [p for p in manifests if json.loads(p.read_text()).get('command') == 'run']
        if not manifests:
            raise click.ClickException(f'no single-worker run to continue under {base}')
        log_root = manifests[-1].parent
        saved = json.loads(manifests[-1].read_text())
        saved.pop('command')
        context = click.get_current_context()
        for key, value in settings.items():
            if context.get_parameter_source(key) != click.core.ParameterSource.COMMANDLINE:
                continue
            if key == 'iterations':
                if value < saved[key]:
                    raise click.UsageError('--iterations cannot be less than the saved total')
            elif key != 'depencity_accept' and value != saved[key]:
                raise click.ClickException('run settings differ from the saved run')
            saved[key] = value
        settings = saved
    if settings['depencity_eval'] and (settings['target'] is None or settings['test_script'] is None):
        raise click.UsageError('--depencity-eval requires --target and --test-script')
    if settings['depencity_accept'] == 'depencity' and not settings['depencity_eval']:
        raise click.UsageError('--depencity-accept requires --depencity-eval')
    if not resume:
        repo, log_root, _ = _build_context(repo, log_root)
    (log_root / 'run.json').write_text(json.dumps(dict(command='run', **settings), indent=2) + '\n')
    click.echo(f'Run: {log_root}')
    repo = Path(settings['repo'])
    task, model, iterations = (settings[key] for key in ('task', 'model', 'iterations'))
    codex = Codex(model, log_root)
    if settings['depencity_eval']:
        runner = EvaluatedRunner(
            codex, repo, task, iterations, Path(settings['target']), tuple(settings['metrics']),
            Path(settings['test_script']), workspace=codex.log_dir / 'workspace', resume=resume,
            depencity_accept=settings['depencity_accept'],
        )
    else:
        runner = InPlaceRunner(codex, repo, task, iterations, resume=resume)
    successful = runner.run()
    if not successful:
        raise click.exceptions.Exit(1)


@main.command()
@click.option('--iterations', type=click.IntRange(1, 1000), default=1, show_default=True,
              help='Total iterations per variant, including completed iterations when continuing.')
@click.option('--continue', 'resume', is_flag=True, help='Continue the latest comparison in --log-root.')
@click.option('--depencity-accept', type=click.Choice(['all', 'depencity']),
              default='all', show_default=True,
              help='Accept passing tests, or require metric improvement for Depencity only. Plain accepts passing tests.')
@click.option('--target', type=click.Path(path_type=Path))
@click.option('--test-script', type=click.Path(path_type=Path))
@click.option('--metric', 'metrics', multiple=True, default=('graph.paths.expressions.count',))
@_common_options
@cli_errors
def run_experiment(repo, log_root, resume, **settings):
    """Run plain and Depencity workers in parallel, optionally filtering by metrics."""
    repo = repo.resolve()
    settings['repo'] = str(repo)
    settings['metrics'] = list(settings['metrics'])
    for key in ('target', 'test_script'):
        if settings[key] is not None:
            settings[key] = str((repo / settings[key]).resolve().relative_to(repo))
    if resume:
        base = (repo / log_root).resolve()
        manifests = sorted(base.glob('*/run.json'))
        if not manifests:
            raise click.ClickException(f'no comparison to continue under {base}')
        log_root = manifests[-1].parent
        saved = json.loads(manifests[-1].read_text())
        context = click.get_current_context()
        for key, value in settings.items():
            if context.get_parameter_source(key) != click.core.ParameterSource.COMMANDLINE:
                continue
            if key == 'iterations':
                if value < saved[key]:
                    raise click.UsageError('--iterations cannot be less than the saved total')
            elif key != 'depencity_accept' and value != saved[key]:
                raise click.ClickException('comparison settings differ from the saved run')
            saved[key] = value
        settings = saved
    else:
        if settings['target'] is None or settings['test_script'] is None:
            raise click.UsageError('run-experiment requires --target and --test-script')
        repo, log_root, _ = _build_context(repo, log_root)
    (log_root / 'run.json').write_text(json.dumps(settings, indent=2) + '\n')
    click.echo(f'Comparison: {log_root}')
    for key in ('repo', 'target', 'test_script'):
        settings[key] = Path(settings[key])
    if not ComparisonRunner(log_root=log_root, resume=resume, **settings).run():
        raise click.exceptions.Exit(1)


@main.command()
@click.option('--workers', type=click.IntRange(1, 100), default=5, show_default=True)
@click.option('--branch-mode', type=click.Choice(['fresh', 'incremental']),
              default='fresh', show_default=True, help='Fresh branch per iteration or one incremental branch per worker.')
@click.option('--iterations', type=click.IntRange(1, 1000), default=1, show_default=True,
              help='Number of iterations per worker.')
@_common_options
@cli_errors
def run_workspaces(repo, workers, task, model, iterations, log_root, branch_mode) -> None:
    """Run workers concurrently using the selected branch strategy."""
    repo, log_root, run_id = _build_context(repo, log_root)
    runner_class = FreshRunner if branch_mode == 'fresh' else IncrementalRunner

    successful = runner_class(Codex(model, log_root), repo, workers, task, iterations, run_id).run()
    if not successful:
        raise click.exceptions.Exit(1)


def _build_context(repo: Path, log_root: Path) -> tuple[Path, Path, str]:
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + f'-{os.getpid()}'

    repo = repo.resolve()
    log_root = (repo / log_root).resolve() / run_id
    log_root.mkdir(parents=True)
    return repo, log_root, run_id

if __name__ == '__main__':
    main()
