"""Utilities shared by agent runner processes."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def acquire_file_semaphore(name: str, capacity: int) -> Iterator[None]:
    """Reserve one slot in a named semaphore shared by local processes."""
    if capacity < 1:
        raise ValueError('Semaphore capacity must be positive')
    if not name or name in {'.', '..'} or '/' in name:
        raise ValueError('Semaphore name must be a single path component')
    lock_dir = Path('/tmp') / f'{name}-{os.getuid()}'
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    slots = [lock_dir / str(index) for index in range(capacity)]
    # Keep the lock files in place so all callers lock the same inodes.
    while True:
        for path in slots:
            with path.open('a') as slot:
                try:
                    fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                yield
                return
        time.sleep(0.1)
