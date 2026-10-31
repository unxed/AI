# Fix-up for unxed/lunobot#262 (tools/train.py)

The working tree already contains the implementation for #262 (see the original task below),
but it is broken: in tools/train.py the constant `MAIN_CI_WAIT_MAX_MIN = 40` and the function
`def main_ci_busy(repo):` were inserted INSIDE `main_push_runs_in_progress` (indented, after its
`return []`), so they are not module-level names and every test calling `train_step` fails
with `NameError: name 'main_ci_busy' is not defined`.

Required:
1. Move `MAIN_CI_WAIT_MAX_MIN` and `main_ci_busy` to module level (zero indentation), placed
   right after the end of `main_push_runs_in_progress` and before `should_cancel_main_run`,
   with normal 4-space indentation of the function body. Remove the nested copies.
2. Keep `train_step`'s call `busy = main_ci_busy(repo)` and the deferral behaviour.
3. Make sure the whole suite passes: `python3 -m unittest discover -s tools -p 'test_*.py'`
   (the new tests in tools/test_train.py for #262 must pass, and all existing tests too).

When you replace a block, give the full replaced text with the exact indentation it must
have in the file; do not rely on the patcher to re-indent it.

---- Original task ----
# train.py: don't merge a train into main while main's CI is running (unxed/lunobot#262)

## Problem

In unxed/f4, `build.yml` cancels the in-progress `main` run when a new push lands on `main`
(`concurrency` + `cancel-in-progress`). Pushes to `main` (mostly the bot's train merges)
arrive more often than a run lasts (20-25 min), so 8 of 14 main runs were cancelled and 52%
of main job-minutes were wasted (22.10-23.10). The bot even cancels its own runs.

## Requested change (item 1 of the issue only)

In `tools/train.py`, `train_step(repo, sign)`: right before the train is merged into `main`
(the fast-forward `PATCH git/refs/heads/main` / `push_ref` and the `gh pr merge` fallback),
check whether `main` has a CI run in progress:

```
GET repos/{repo}/actions/workflows/build.yml/runs?branch=main&event=push&status=in_progress
GET repos/{repo}/actions/workflows/build.yml/runs?branch=main&event=push&status=queued
```

If any run is in progress or queued, do NOT merge in this cycle: print a clear Russian
status line in the style of the surrounding messages (e.g. `поезд #N ждёт: на main идёт CI
(прогон <id>), вливание отложено до следующего цикла`) and `return 0` (the next tick retries;
the train is not in a hurry). Exceptions / rules:
- Defer at most ~40 minutes per train: if main's in-progress run started more than
  `MAIN_CI_WAIT_MAX_MIN = 40` minutes ago (`run_started_at`/`created_at`), merge anyway
  (a stuck run must not block trains forever).
- Only for repos whose `build.yml` exists; if the API call fails or the workflow is absent
  (404 / error), do not block the merge (same defensive style as `main_push_runs_in_progress`:
  failures of gh never break the tick).
- Put the check in a small helper, e.g. `main_ci_busy(repo) -> run dict | None`, next to
  `main_push_runs_in_progress`, with a Russian docstring referencing unxed/lunobot#262.
- Keep everything else in `train_step` unchanged (cancel-after-ff logic, tags, «Пробуйте!»).

Out of scope: item 2 (single push from staging) and the modules/merge.md numbers.

## Acceptance tests (tools/test_train.py, `unittest`, offline, in the existing style)

- main has an in-progress build.yml push run that started 5 min ago → `train_step` does not
  merge (no PATCH of refs/heads/main, no `gh pr merge`), prints the waiting line, returns 0.
- queued run → same.
- run started 50 min ago → merge proceeds as before.
- API failure / no build.yml → merge proceeds as before.
- Existing tests keep passing.

Test command: `python3 -m unittest discover -s tools -p 'test_*.py'`.
Mirror how test_train.py already stubs `api`/`run` for `train_step`.
