import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec

import pytest

from agent_runner import runner

from .utils import DOCKER, FIXTURES


# Fixture Python files are inputs.
collect_ignore = ['fixtures']


@pytest.fixture
def mock_path_writes(monkeypatch):
    mkdir = create_autospec(Path.mkdir)
    write_text = create_autospec(Path.write_text)
    replace = create_autospec(Path.replace)
    monkeypatch.setattr(Path, 'mkdir', mkdir)
    monkeypatch.setattr(Path, 'write_text', write_text)
    monkeypatch.setattr(Path, 'replace', replace)
    return mkdir, write_text, replace


@pytest.fixture
def fake_which(monkeypatch):
    paths = {
        'codex': str(FIXTURES / 'bin/codex'),
        'depencity': str(FIXTURES / 'bin/depencity'),
        'docker': str(DOCKER),
    }
    which = Mock(side_effect=paths.__getitem__)
    monkeypatch.setattr(shutil, 'which', which)
    return which


@pytest.fixture
def fixed_runner_metadata(monkeypatch):
    monkeypatch.setattr(
        runner, 'datetime', SimpleNamespace(now=lambda tz: datetime(2026, 1, 2, 3, 4, 5, tzinfo=tz)),
    )
    monkeypatch.setattr(runner, 'os', SimpleNamespace(getpid=lambda: 42))
    monkeypatch.setattr(runner, 'version', lambda package: {'depencity': '1.2.3'}[package])
