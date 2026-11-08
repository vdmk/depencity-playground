"""Shared worker scheduling and Codex iteration execution."""

import signal
import subprocess
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed

import click


class Runner(ABC):
    """Schedule workers and execute Codex iterations."""

    def __init__(self, codex, repo, count, task, iterations):
        self.codex = codex
        self.repo = repo
        self.count = count
        self.task = (
            f'{task} Do not commit changes. '
            'Return a short_summary describing the change in one line. '
            'The agent caller will commit as "auto-refactor: {short_summary}".'
        )
        self.iterations = iterations
        self.stopping = False

    def run(self) -> bool:
        previous_handler = signal.signal(signal.SIGINT, self.handle_interrupt)
        try:
            with ThreadPoolExecutor(max_workers=self.count) as workers:
                futures = {}
                for number in range(1, self.count + 1):
                    name = f'agent-{number:02d}'
                    futures[workers.submit(self.run_worker, name)] = name
                successful = True
                for future in as_completed(futures):
                    try:
                        successful &= future.result()
                    except (OSError, subprocess.CalledProcessError) as error:
                        click.echo(f'{futures[future]}: stopped after runner error ({error})')
                        successful = False
            click.echo('All current runs stopped; not relaunching agents.' if self.stopping
                       else 'No agents remain; stopping.')
            return successful
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    def handle_interrupt(self, _signum, _frame):
        if self.stopping:
            raise KeyboardInterrupt
        self.stopping = True
        click.echo('Stopping after current runs; press Ctrl+C again to interrupt the runner.')

    @abstractmethod
    def run_worker(self, name):
        pass

    def run_iteration(self, name, iteration, work_dir):
        click.echo(f'{name}.{iteration}: launching')
        result = self.codex.run(f'{name}.{iteration}', work_dir, self.task)
        click.echo(f'{name}.{iteration}: finished with return code {result.return_code}')
        if result.return_code != 0:
            click.echo(f'{name}: stopped after nonzero exit')
        return result
