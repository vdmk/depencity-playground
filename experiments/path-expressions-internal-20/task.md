Refactor calculator.py for readability and simpler behavior-preserving code. Do not merely relocate complexity. Do not commit or modify test_calculator.py.

Perform 20 internal refactoring attempts within this single agent turn. An attempt is one concrete candidate edit, followed by measurement and a keep/revert decision. Complete all 20 even if several consecutive attempts fail to improve the code. Rejected attempts count; ideas without edits and measurement do not. Do not repeatedly submit the same rejected transformation.

Use graph.paths.expressions.count as the acceptance metric. Measure the aggregate for the entire calculator.py file, including all descendant scopes, using Depencity profiling MCP. Use the same query and metric before and after every attempt; request only this metric with depth 0. Never move code outside calculator.py to lower the metric.

Before starting, measure the original file, run test_calculator.py through Docker MCP, and save a copy of calculator.py as the current accepted checkpoint. If baseline tests fail or profiling is unavailable, report the blocker and stop rather than inventing measurements.

For each attempt from 1 through 20:
1. Start from the latest accepted checkpoint and choose a distinct, coherent simplification. Explore different sources of complexity instead of repeatedly rewriting the parser in the same way.
2. Save the current checkpoint and its measured complexity, then implement the candidate in calculator.py.
3. Measure the candidate with the same whole-file query and run the original test_calculator.py through Docker MCP. Inspect readability and behavior preservation as well as the number.
4. Keep the candidate only if all tests pass, its measured expression-path count is strictly lower than the current checkpoint, and the code is clearer without relocating complexity. Otherwise restore the checkpoint completely before the next attempt. Equal complexity is a rejection. Never compare only against the original baseline.
5. Append a record to attempts.jsonl in your workspace: attempt number, concrete change, before count, candidate count, test result, accepted boolean, and decision reason. Record tool failures honestly; do not treat them as passing validation. Include rejected candidates in the log.

Do not stop at a plateau or after the first success. You must try 20 candidates, not obtain 20 accepted changes. If an external failure prevents completion, preserve the last validated checkpoint and report exactly how many attempts completed and the blocker.

Finally, restore the latest accepted checkpoint, remeasure it, rerun the original tests through Docker MCP, and report completed attempts, accepted attempts, original and final complexity, and test results in your short summary. Leave attempts.jsonl available for inspection.
