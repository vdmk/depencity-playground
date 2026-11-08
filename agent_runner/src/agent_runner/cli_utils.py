"""Helpers for reporting command-line errors."""

import subprocess
from functools import wraps

import click


def cli_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise click.ClickException(str(error)) from error
    return wrapped
