# Expressions and calls v2

Copies `../expressions-and-calls` with the same source, model, variants,
20 iterations per variant, three metrics, and disabled metric acceptance gate.
The task prompt changes only the test filename to `test_long_words_v2.py`.

The copied tests retain the original behavior cases and add a pytest-benchmark
case with 64,000 words, half selected. Pytest prints the timing table on every
run. Repeated list concatenation is costly at this size and will show up in the
measurements. Timing is reported without a performance acceptance threshold;
there is no memory benchmark.

Run:

```sh
uv run agent-runner run experiments/long-words/expressions-and-calls-v2/experiment.toml
```
