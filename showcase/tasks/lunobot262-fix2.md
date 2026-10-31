# Fix-up 2 for unxed/lunobot#262 (tools/train.py)

`MAIN_CI_WAIT_MAX_MIN = 40` and `def main_ci_busy(repo):` sit INSIDE
`main_push_runs_in_progress` (indented by 8, after its `return []`), so `train_step` fails with
`NameError: name 'main_ci_busy' is not defined`.

IMPORTANT about the patcher: a REPLACE whose content only changes indentation is a no-op for
it (it re-indents the content to the matched snippet). So do it in TWO modifications:
1. `DELETE` the nested block: the indented `MAIN_CI_WAIT_MAX_MIN = 40` line and the whole
   indented `def main_ci_busy(repo):` function (all its lines), leaving
   `main_push_runs_in_progress` ending with `return []`.
2. `INSERT_BEFORE` the top-level line `def should_cancel_main_run(repo):` the same code at
   module level (column 0, function body indented by 4), followed by two blank lines.

Do not change anything else. Test command:
`python3 -m unittest discover -s tools -p 'test_*.py'` (all tests, incl. the #262 ones, must pass).
