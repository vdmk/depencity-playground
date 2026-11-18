Refactor long_words.py into readable, 
simple functions with minimal semantic complexity.
Preserve behavior, edit the copied file in place,
and run test_long_words_v2.py through Docker MCP.
Optimize only graph.paths.expressions.count, call.occurrences.total.count, and call.dependencies.external.distinct_count.

The objective is to minimize the whole-file 
expression-path count, call count, and distinct external call dependencies. 
Do not make speculative or unrelated edits. 
Refactor only long_words.py; do not commit. 
Keep the change focused on one cohesive area.

Inspect the pytest-benchmark results before and after your change. Do not degrade benchmark performance.
Also inspect the memory table printed by the tests before and after your change. Do not increase peak memory usage.
