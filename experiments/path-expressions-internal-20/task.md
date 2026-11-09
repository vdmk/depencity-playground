Refactor calculator.py for readability and simpler behavior-preserving code without relocating complexity. Edit only calculator.py; do not commit, modify test_calculator.py, or create other files. Keep accepted checkpoint source in conversation context.

Complete 20 distinct internal attempts in this turn, including after a plateau or success. Each attempt requires a concrete edit, measurement, tests, and a keep/revert decision; rejected attempts count. Explore different simplifications rather than repeating rejected transformations.

Measure graph.paths.expressions.count using Depencity profiling MCP: whole-file aggregate including descendant scopes, depth 0, only this metric, with the same query throughout. First measure the baseline and run test_calculator.py through Docker MCP; stop if baseline tests fail.

For each attempt:
1. Start from the latest accepted checkpoint, retain its source and count in context, and implement one coherent simplification.
2. Re-measure and run the original tests through Docker MCP.
3. Keep only if tests pass, complexity strictly decreases from that checkpoint, and readability improves without relocating complexity. Otherwise restore the checkpoint completely, including for equal counts.
4. Report a progress message with attempt number, change, before/candidate counts, test result, accepted boolean, and reason. Include rejections and tool failures; never treat tool failures as passing validation. The runner captures messages outside the project directory.

Finish with the latest accepted source, re-measure and rerun tests, then summarize completed/accepted attempts, baseline/final counts, and test results. If an external failure prevents completion, preserve the last validated checkpoint and report completed attempts and the blocker.
