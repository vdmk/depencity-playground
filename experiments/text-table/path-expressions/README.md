# Text-table expression paths

A 35-line plain-text table formatter with optional headers, ragged rows,
multiline cells, string conversion, and iterable inputs. Widths count Python
characters; output trims trailing whitespace. This is a new fixture, not code
extracted from an external project.

Run a short pilot with three iterations each for Depencity and plain:

```sh
uv run agent-runner run experiments/text-table/path-expressions/experiment.toml
```

Both variants receive the same task and must pass the original behavior tests.
Only Depencity receives profiling tools. Whole-file expression paths are the
sole objective; the harness accepts all passing candidates, allowing the pilot
to reveal regressions as well as improvements. There is no fixed internal
candidate-attempt budget. Results go to
`out/experiments/text-table/path-expressions/RUN_ID/`.
