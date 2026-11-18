Refactor long_words.py into readable, 
simple functions with minimal semantic complexity.
Preserve behavior, edit the copied file in place,
and run test_long_words_v2.py through Docker MCP.
Optimize graph.paths.expressions.count, call.occurrences.total.count, call.dependencies.external.distinct_count, benchmark runtime, and peak memory usage.

The objective is to minimize the whole-file 
expression-path count, call count, distinct external call dependencies, benchmark runtime, and peak memory usage.
Do not make speculative or unrelated edits. 
Refactor only long_words.py; do not commit. 
Keep the change focused on one cohesive area.

Inspect the pytest-benchmark results before and after your change. Do not degrade benchmark performance.
Also inspect the memory table printed by the tests before and after your change. Do not increase peak memory usage.
