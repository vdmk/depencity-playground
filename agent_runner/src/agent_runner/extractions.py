"""Check same-module coordinator extractions against the previous commit."""

import os
import subprocess
from pathlib import Path

from depencity import NodeKind, ScopeKind, build, profile


def extraction_failures(before, after):
    def functions(source):
        return {
            scope.path(): scope for scope in build(source).walk_scopes()
            if scope.kind == ScopeKind.FUNCTION
        }

    previous = functions(before)
    current = functions(after)
    helpers = {current[name] for name in current.keys() - previous.keys()}
    for name in sorted(previous.keys() & current.keys()):
        caller = current[name]
        called = {
            target for node in caller.nodes if node.kind == NodeKind.CALL
            for target in node.collect_call_targets()[0] if target in helpers
        }
        if not called:
            continue
        before_count = profile(previous[name]).graph__paths__expressions__count
        after_count = profile(caller).graph__paths__expressions__count
        for helper in sorted(called, key=lambda scope: scope.path()):
            helper_count = profile(helper).graph__paths__expressions__count
            if (None in (before_count, after_count, helper_count)
                    or after_count + helper_count >= before_count or helper_count <= after_count):
                yield (f'{name} -> {helper.path()}: source_before={before_count}, '
                       f'source_after={after_count}, helper_after={helper_count}')


def candidate_extraction_failures(workspace: Path):
    paths = subprocess.check_output(
        ['git', 'diff', '--no-renames', '--name-only', '-z', '--diff-filter=M',
         'HEAD', '--', '*.py'], cwd=workspace,
    )
    for raw_path in paths.split(b'\0')[:-1]:
        path = os.fsdecode(raw_path)
        before = subprocess.check_output(['git', 'show', f'HEAD:{path}'], cwd=workspace)
        for failure in extraction_failures(before, (workspace / path).read_bytes()):
            yield f'{path}: {failure}'
