"""Run an MCP agent with a strict expression-path target on the calculator."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from agent_runner.mcp import _docker_test
from depencity.mcp import profile as mcp_profile


MODEL = 'gpt-6-luna'
DEFAULT_TURNS = 3
PROMPT = (
    'Refactor the target Python script into readable, simple functions with minimal '
    'semantic complexity. Preserve behavior, edit the copied file in place, and run '
    'the provided tests. Optimize only graph.paths.expressions.count. Use the profile '
    'as evidence: inspect the module scope with all children so you can compare each '
    'scope\'s direct and subgraph expression-path counts. Preserve behavior and '
    'dependency meaning; do not merely relocate complexity. Search within this '
    'invocation. You have a budget of exactly 10 candidate attempts inside this '
    'invocation. The objective is to minimize the whole-file expression-path count, '
    'not merely to find one improvement. For each attempt, make a candidate, run the tests and profile, and '
    'revert it immediately if the expression-path count does not decrease. After every '
    'rejection, deliberately change perspective: inspect a different workflow, '
    'repeated concept, abstraction boundary, local detail, or larger module structure, '
    'and try a materially different refactoring. Do not retry the same idea with '
    'cosmetic variations. Continue searching through the full 10 attempts when '
    'necessary, including larger coherent simplifications after smaller ones fail. '
    'Keep the best tested state found so far, and continue searching after every '
    'improvement; do not stop at the first accepted candidate. Stop only after all '
    '10 attempts have been used, leaving the best behavior-preserving state in the '
    'file. Do not finish after a rejected candidate, after reporting that no improvement '
    'was found, or with the file unchanged. Do not make speculative or unrelated edits. '
    'The harness accepts a turn when tests pass; it records a strict decrease when '
    'one is found and otherwise records a tested no-change turn.'
)


@dataclass
class TurnResult:
    turn: int
    exit_code: int
    duration_seconds: float
    changed: bool
    diff: str
    profile: str
    profile_metrics: dict[str, object]
    test_exit_code: int
    tests: str
    response: str
    mcp_tool_calls: int
    command_calls: int
    log: str


def main() -> None:
    args = _parse_args()
    repo = Path(__file__).resolve().parents[2]
    source = repo / 'experiments' / 'fixtures' / 'calculator.py'
    test_source = repo / 'experiments' / 'fixtures' / 'test_calculator.py'
    base = repo / 'out' / 'experiments' / 'strict-targeted'
    if args.resume:
        root = _find_resumable_run(base, args.resume)
        turns = args.turns or _infer_turns(root)
        original = source.read_text()
        original_tests = test_source.read_text()
        original_profile_path = root / 'original-profile.txt'
        if not original_profile_path.exists():
            raise SystemExit(f'resumable run is missing {original_profile_path}')
        original_profile = original_profile_path.read_text()
        original_metrics = _parse_profile(original_profile)
    else:
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}'
        root = base / run_id
        root.mkdir(parents=True, exist_ok=False)
        turns = args.turns or DEFAULT_TURNS
        original = source.read_text()
        original_tests = test_source.read_text()
        original_profile, original_metrics = _profile(repo, source)
        (root / 'original-profile.txt').write_text(original_profile)
    variants = ('mcp',)
    with ThreadPoolExecutor(max_workers=len(variants)) as executor:
        futures = {
            variant: executor.submit(
                _run_variant,
                repo,
                root,
                variant,
                source.name,
                original,
                test_source.name,
                original_tests,
                turns,
                resume=args.resume,
            )
            for variant in variants
        }
        results = {variant: futures[variant].result() for variant in variants}
    document = {
        'target': source.name,
        'model': MODEL,
        'turns': turns,
        'original_profile': str(root / 'original-profile.txt'),
        'original_profile_metrics': original_metrics,
        'results': {variant: [asdict(turn) for turn in turns] for variant, turns in results.items()},
    }
    output = root / 'comparison.json'
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    print(json.dumps(document, indent=2, sort_keys=True))
    print(f'comparison written to {output}')


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns', type=int)
    parser.add_argument(
        '--resume', nargs='?', const='latest', metavar='RUN_ID',
        help='Resume an incomplete run, selecting the latest one unless RUN_ID is given.',
    )
    args = parser.parse_args()
    if args.turns is not None and args.turns < 1:
        parser.error('--turns must be positive')
    return args


def _find_resumable_run(base: Path, run_id: str) -> Path:
    if run_id != 'latest':
        root = base / run_id
        if not root.is_dir():
            raise SystemExit(f'run not found: {root}')
        if (root / 'comparison.json').exists():
            raise SystemExit(f'run is already complete: {root}')
        return root
    runs = sorted((path for path in base.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
    for root in reversed(runs):
        if not (root / 'comparison.json').exists():
            return root
    raise SystemExit(f'no incomplete run found under {base}')


def _infer_turns(root: Path) -> int:
    turns = [
        int(path.stem.rsplit('-', 1)[-1])
        for path in root.glob('*-step-*.jsonl')
        if path.stem.rsplit('-', 1)[-1].isdigit()
    ]
    return max(turns, default=DEFAULT_TURNS)


def _run_variant(
    repo: Path,
    root: Path,
    variant: str,
    target_name: str,
    original: str,
    test_name: str,
    original_tests: str,
    turns: int,
    *,
    resume: bool,
) -> list[TurnResult]:
    directory = root / variant
    target = directory / target_name
    if not resume:
        directory.mkdir(parents=True)
        target.write_text(original)
        (directory / test_name).write_text(original_tests)
    elif not directory.exists():
        directory.mkdir(parents=True)
        target.write_text(original)
        (directory / test_name).write_text(original_tests)
    results, start = _load_completed_turns(root, variant, turns)
    previous = _restore_previous_source(root, directory, target, target_name, original, start)
    previous_metrics = _previous_metrics(root, variant, start)
    for turn in range(start, turns + 1):
        result = _run_turn(
            repo, root, directory, target, variant, turn, target_name, previous,
            previous_metrics, test_name,
        )
        results.append(result)
        previous = target.read_text() if target.exists() else ''
        previous_metrics = result.profile_metrics
        (root / f'{variant}-step-{turn:02d}-source.py').write_text(previous)
    return results


def _load_completed_turns(root: Path, variant: str, turns: int) -> tuple[list[TurnResult], int]:
    results: list[TurnResult] = []
    for turn in range(1, turns + 1):
        prefix = root / f'{variant}-step-{turn:02d}'
        required = [
            prefix.with_suffix('.jsonl'),
            prefix.with_suffix('.diff'),
            Path(f'{prefix}-profile.txt'),
            Path(f'{prefix}-tests.txt'),
            Path(f'{prefix}-response.txt'),
        ]
        if not all(path.exists() for path in required):
            return results, turn
        log = prefix.with_suffix('.jsonl')
        mcp_calls, command_calls, _ = _parse_output(log)
        results.append(TurnResult(
            turn=turn,
            exit_code=0,
            duration_seconds=0,
            changed=bool(Path(f'{prefix}.diff').read_text()),
            diff=str(Path(f'{prefix}.diff')),
            profile=str(Path(f'{prefix}-profile.txt')),
            profile_metrics=_parse_profile(Path(f'{prefix}-profile.txt').read_text()),
            test_exit_code=0,
            tests=str(Path(f'{prefix}-tests.txt')),
            response=str(Path(f'{prefix}-response.txt')),
            mcp_tool_calls=mcp_calls,
            command_calls=command_calls,
            log=str(log),
        ))
    return results, turns + 1


def _restore_previous_source(
    root: Path,
    directory: Path,
    target: Path,
    target_name: str,
    original: str,
    start: int,
) -> str:
    if start == 1:
        target.write_text(original)
        return original
    snapshot = root / f'{directory.name}-step-{start - 1:02d}-source.py'
    if not snapshot.exists():
        # Older runs did not save snapshots. Their current target is the best
        # available state after the interrupted agent attempt, so restart from it.
        previous = target.read_text() if target.exists() else original
        target.write_text(previous)
        return previous
    previous = snapshot.read_text()
    target.write_text(previous)
    return previous


def _run_turn(
    repo: Path,
    root: Path,
    directory: Path,
    target: Path,
    variant: str,
    turn: int,
    target_name: str,
    previous: str,
    previous_metrics: dict[str, object],
    test_name: str,
) -> TurnResult:
    prefix = f'{variant}-step-{turn:02d}'
    log = root / f'{prefix}.jsonl'
    prompt = (
        f'{PROMPT}\nRefactor only {target_name}; do not commit. Keep the change focused '
        'on one cohesive area.'
    )
    command = _command(repo, directory, variant == 'mcp', prompt)
    started = time.monotonic()
    with log.open('w') as output:
        process = subprocess.run(command, cwd=directory, stdout=output, stderr=subprocess.STDOUT)
    duration = time.monotonic() - started
    edited = target.read_text() if target.exists() else ''
    before_name = 'original' if turn == 1 else f'step-{turn - 1:02d}'
    diff = ''.join(difflib.unified_diff(
        previous.splitlines(keepends=True),
        edited.splitlines(keepends=True),
        fromfile=f'{before_name}/{target_name}',
        tofile=f'step-{turn:02d}/{target_name}',
    ))
    diff_path = root / f'{prefix}.diff'
    diff_path.write_text(diff)
    profile, metrics = _profile(repo, target)
    profile_path = root / f'{prefix}-profile.txt'
    profile_path.write_text(profile)
    test_result = json.loads(
        _docker_test(
            str(directory),
            repo,
            repo,
            repo / 'docker/test/Dockerfile',
            command=(
                "sh -c 'cd /workspace/"
                f"{directory.relative_to(repo)}"
                " && pytest -q test_calculator.py "
                "-p no:cacheprovider'"
            ),
        )
    )
    tests_path = root / f'{prefix}-tests.txt'
    tests_path.write_text(test_result['output'])
    if process.returncode != 0 or test_result['returncode'] != 0:
        target.write_text(previous)
        raise RuntimeError(f'{variant} turn {turn} failed; see {tests_path}')
    if not _strictly_improves(previous_metrics, metrics):
        target.write_text(previous)
        diff_path.write_text('')
        previous_profile_path = (
            root / 'original-profile.txt'
            if turn == 1
            else root / f'{variant}-step-{turn - 1:02d}-profile.txt'
        )
        profile_path.write_text(previous_profile_path.read_text())
        metrics = previous_metrics
        edited = previous
    mcp_calls, command_calls, response = _parse_output(log)
    response_path = root / f'{prefix}-response.txt'
    response_path.write_text(response)
    return TurnResult(
        turn=turn,
        exit_code=process.returncode,
        duration_seconds=round(duration, 3),
        changed=edited != previous,
        diff=str(diff_path),
        profile=str(profile_path),
        profile_metrics=metrics,
        test_exit_code=test_result['returncode'],
        tests=str(tests_path),
        response=str(response_path),
        mcp_tool_calls=mcp_calls,
        command_calls=command_calls,
        log=str(log),
    )


def _previous_metrics(root: Path, variant: str, start: int) -> dict[str, object]:
    if start == 1:
        return _parse_profile((root / 'original-profile.txt').read_text())
    return _parse_profile(
        (root / f'{variant}-step-{start - 1:02d}-profile.txt').read_text()
    )


def _strictly_improves(before: dict[str, object], after: dict[str, object]) -> bool:
    return after.get('subgraph_profile.graph.paths.expressions.count', 0) < before.get(
        'subgraph_profile.graph.paths.expressions.count', 0
    )


def _profile(repo: Path, target: Path) -> tuple[str, dict[str, object]]:
    response = mcp_profile(
        path=str(target),
        workspace=str(repo),
        detail='compact',
    )
    document = json.loads(response)
    profile = json.dumps(document, indent=2, sort_keys=True) + '\n'
    return profile, _flatten_metrics(document)


def _parse_profile(profile: str) -> dict[str, object]:
    return _flatten_metrics(json.loads(profile))


def _flatten_metrics(value: object, prefix: str = '') -> dict[str, object]:
    if not isinstance(value, dict):
        return {prefix: value} if prefix else {}
    metrics: dict[str, object] = {}
    for key, item in value.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(item, dict):
            metrics.update(_flatten_metrics(item, name))
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            metrics[name] = item
    return metrics


def _command(repo: Path, directory: Path, with_mcp: bool, prompt: str) -> list[str]:
    command = ['codex', 'exec', '--ephemeral', '--json', '--ignore-user-config']
    if with_mcp:
        command.extend(_mcp_options(repo, directory))
    command.extend([
        '--sandbox', 'workspace-write', '--config', 'approval_policy="on-request"',
        '--cd', str(directory), '--model', MODEL, prompt,
    ])
    return command


def _mcp_options(repo: Path, directory: Path) -> list[str]:
    return [
        '--config', 'mcp_servers.depencity.command="uv"',
        '--config', 'mcp_servers.depencity.args=' + json.dumps([
            'run', '--project', str(repo), 'depencity-mcp', '--workspace', str(directory),
        ]),
        '--config', f'mcp_servers.depencity.cwd={json.dumps(str(directory))}',
        '--config', 'mcp_servers.depencity.default_tools_approval_mode="approve"',
        '--config', 'mcp_servers.agent-runner.command="uv"',
        '--config', 'mcp_servers.agent-runner.args=' + json.dumps([
            'run', '--project', str(repo), 'agent-runner-mcp', '--workspace', str(directory),
            '--build-root', str(repo), '--dockerfile', 'docker/test/Dockerfile',
        ]),
        '--config', f'mcp_servers.agent-runner.cwd={json.dumps(str(directory))}',
        '--config', 'mcp_servers.agent-runner.default_tools_approval_mode="approve"',
        '--config', 'mcp_servers.agent-runner.enabled_tools=["docker_test", "reviewed_commits"]',
    ]


def _parse_output(log: Path) -> tuple[int, int, str]:
    mcp_calls = command_calls = 0
    responses: list[str] = []
    for line in log.read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get('item', {})
        item_type = item.get('type')
        if item_type == 'mcp_tool_call':
            mcp_calls += 1
        elif item_type == 'command_execution':
            command_calls += 1
        if item_type != 'agent_message':
            continue
        text = item.get('text')
        if isinstance(text, str):
            responses.append(text)
            continue
        responses.extend(
            block['text'] for block in item.get('content', [])
            if isinstance(block, dict) and isinstance(block.get('text'), str)
        )
    return mcp_calls, command_calls, '\n\n'.join(responses)


if __name__ == '__main__':
    main()
