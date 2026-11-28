from contextlib import ExitStack
from unittest.mock import Mock
from uuid import uuid4

import pytest

from agent_runner import utils


@pytest.mark.parametrize(('name', 'capacity', 'message'), (
    ('docker-checks', 0, 'capacity must be positive'),
    ('nested/docker-checks', 1, 'name must be a single path component'),
))
def test_file_semaphore_rejects_invalid_configuration(name, capacity, message):
    with pytest.raises(ValueError, match=message):
        with utils.acquire_file_semaphore(name, capacity):
            pytest.fail('Invalid configuration acquired a slot')


def test_file_semaphore_retries_when_all_slots_are_held(monkeypatch):
    name = f'test-file-semaphore-{uuid4().hex}'
    with ExitStack() as held:
        held.enter_context(utils.acquire_file_semaphore(name, 2))
        held.enter_context(utils.acquire_file_semaphore(name, 2))
        sleep = Mock(side_effect=lambda _delay: held.close())
        monkeypatch.setattr(utils.time, 'sleep', sleep)

        with utils.acquire_file_semaphore(name, 2):
            sleep.assert_called_once()
