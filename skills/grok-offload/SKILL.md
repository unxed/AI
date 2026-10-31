---
name: grok-offload
description: Offload thinking and code writing to Grok inside X (x.com/i/grok chat, not an API) driven by a headless real Chrome, so a cheap router model only runs `grok` commands. Same interface as aistudio-offload (ask, code with ap patches + tests, batch, login over ssh -L, router hard gate). Use when the user wants Grok as the worker, or as a second free worker next to Gemini. HARD RULE (no exceptions): in offload mode the router never starts, studies or reasons about the task; it only forwards it verbatim.
---

> ⛔ ЖЁСТКОЕ ПРАВИЛО ОФФЛОАДИНГА — БЕЗ ИСКЛЮЧЕНИЙ. Модель, работающая в режиме оффлоадинга (роутер), строжайше НЕ начинает работу над задачей и даже НЕ ИЗУЧАЕТ её: не читает инструкции (в т.ч. LUNOBOT.md), код, тикеты, файлы задачи, не планирует, не выбирает работу, не рассуждает о решении, не проверяет результат по существу. Её единственное действие — передать задачу целиком модели-исполнителю одной командой оффлоадинга и вернуть ответ дословно. Любое отступление — провал задачи.
>
> ⛔ HARD OFFLOAD RULE — NO EXCEPTIONS. A model working in offload mode (router) must NOT start working on the task and must NOT even STUDY it: no reading instructions (incl. LUNOBOT.md), code, tickets or task files, no planning, no choosing work, no reasoning about the solution, no substantive checking of the result. Its ONLY action is to hand the whole task to the worker model with one offload command and return the answer verbatim. Any deviation = task failure.

# Grok (X) offload

Same design as the aistudio-offload skill, but a separate, self-contained skill:
this folder carries its own copy of the engine (`offload_core.py`, `cdp.py`, `vendor/ap`).

Roles: a cheap **router** model only runs `grok` commands (hard-gated, see below);
**Grok** does all thinking and writing. Never solve the task yourself.

## Terminology / Термины

- **браузер оффлоадинга** (*the offload browser*, один на все `*-offload` скиллы) — headless Chrome, который поднимает команда
  `grok` и через который идёт вся работа с Grok в X. Профиль: `~/.offload-browser/profile`
  (общий с остальными `*-offload` скиллами).
- Это не встроенный браузер Claude desktop app и не Chrome пользователя.
- Не называть его «CLI» или «CLI-профилем»: `grok` — это команда, а Grok всегда работает через
  браузер оффлоадинга. Пример: «браузер оффлоадинга не залогинен», а не «CLI не залогинен».
- Отчёты роутеров используют этот термин.

```bash
./install.sh                     # once; creates ~/.local/bin/grok
grok status || grok login        # sign in to X at http://127.0.0.1:8766/ (ssh -L on VMs)
grok ask "question"              # -m fast (default) | auto | expert
grok code --task-file t.md -C ~/repo -t "go test ./..."   # ap patch, applied + tested
grok batch jobs.jsonl -j 2
```

Notes:
- State lives in `~/.offload-browser` (profile `profile/`, shared with the other `*-offload` skills).
- Prompts over ~50k characters (e.g. `code` with a codebase) are attached as a `.txt` file;
  the X upload accepts .txt/.md/.json/.csv/.pdf but not archives, so sources are packed
  into text (`=== BEGIN path ===` blocks).
- The answer is read from X's chat WebSocket (`CHANNEL_ASSISTANT_RESPONSE` chunks), so it
  is raw markdown with code fences intact; thinking chunks are skipped.
- `grok code` sends tracked repo files + the [`ap`](https://github.com/unxed/ap) patch spec;
  Grok's patch is applied and the `-t` test command run; failures go back for `-r 4` rounds.
- If X says "we temporarily restricted login" in `grok login`, use the page's
  "Paste cookies" box: `auth_token=...; ct0=...` from DevTools of a browser where you are
  logged in to X.

## Router with a hard gate

`agents/claude/grok-router.md` (Claude Code: `tools: Bash` + `PreToolUse` hook `grok guard`,
install to `~/.claude/agents/`) and `agents/opencode/grok-router.md` (opencode: bash allowed
only for `grok …`). The gate blocks anything except a single `grok ask|code|batch|status|serve`
command — no chaining, redirects, substitutions or file writes.

**Small cloud VMs (< 2 GB RAM, e.g. GCP e2-micro): never build or test locally.** Use
`--ci` instead of `-t`: each round's patch is committed to a branch (`--ci-branch`,
default `offload/<timestamp>`), pushed, a **draft PR** is opened against `--ci-base`
(default `main`; most workflows run on `pull_request`) and the GitHub Actions runs of
that commit are awaited; failed-step logs go back to the model. Needs `gh auth login`.
`code -t` refuses to run on such machines (override: `OFFLOAD_ALLOW_LOCAL_BUILD=1`).

```bash
grok code --task-file task.md -C ~/repo --ci --ci-branch fix/issue-42
```

## Vendor chain (hard rule)

A vendor never offloads to itself, directly or anywhere up a chain (no Gemini planning work
for Gemini, no Haiku→Gemini→…→Gemini). Every ask/code/batch call needs `OFFLOAD_CALLER=<model>`
(auto-detected as `anthropic` inside Claude Code) and honours `OFFLOAD_CHAIN` (e.g.
`anthropic>google`): if the worker's vendor is already in it, the call is refused. The extended
chain is exported to child processes (e.g. the `-t` test command) and printed on stderr — pass
it as `OFFLOAD_CHAIN=...` to any sub-task derived from the answer.

## Manager gate, context size, diagnostics

- **Web UI only (hard rule)**: Grok in X (x.com/i/grok) is reached only through the browser UI driven over CDP. Never add or use an API path; never use its API, API keys or SDKs.
- **The main agent never does the work itself** when offloading: no code, analysis, triage, texts or markdown
  edits of its own. Write a task file and hand it to the router subagent.
- **Manager gate**: make a small orchestrator model unable to cheat with the PreToolUse hook `grok guard --manager`
  (blocks Edit/MultiEdit/NotebookEdit, Write except `task*.md`/`*.task.md`/`tasks/`, and inline code or file writes in
  Bash: `python3 -c`, heredocs, `sed -i`, `perl -e/-i`, `tee`, `> file`, `git apply`/`patch`/`ap`, `gh --body "..."`):
  `claude -p --settings '{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"grok guard --manager"}]}]}}'`
- **Explicit `-p` paths and quota**: `-p` paths that git does not track are packed from disk (a path matching no files exits 3 naming it; per-path counts in the `context paths:` log line); when every model of the chain fails with quota/rate limit/empty answer, the engine waits `OFFLOAD_QUOTA_WAIT` s (default 120) and makes one more pass.
- **Context size**: the packed context (+task) is limited to 400000 chars (`--max-context N` on `code`/`ask`, or
  `OFFLOAD_MAX_CONTEXT`). Nothing is ever truncated: over the limit the command exits with code 3 and lists the 15
  largest files. `code` on a big repo needs `-p <paths...>`; for `ask` pass fewer `-f`. Every call logs
  `context: N files, M chars`.
- **Diagnostics**: every failed model request saves `~/.offload-browser/diag/<UTC>-<pid>/` (`summary.txt`, `page.txt`,
  `screenshot.jpg`, `alerts.txt`) and prints `DIAG <REASON> <dir>: <message>`. Reasons: STALLED QUOTA RATE_LIMIT
  PERMISSION_DENIED CONTEXT_TOO_LARGE NOT_LOGGED_IN SAFETY EMPTY_ANSWER TIMEOUT UI_CHANGED PATCH_FAILED TESTS_FAILED
  UNKNOWN. `grok diag [N]` prints the last N summaries (routers may run it).
  - `grok code` fails loudly with `DIAG PATCH_NOOP` (non-zero) when `ap` exits 0 but the patch left the working tree unchanged or left one of its target files untouched (live: "reported success" while the file was not changed); it logs `files changed (N): ...` after every applied patch, and the model is told to resend a real change.
  - A response stream that is not valid JSON (truncated, or an error chunk such as `[,[7,"The caller does not have permission"]]` appended after the text; live: "Expecting ',' delimiter") is no longer an opaque JSON error: an error chunk becomes `AI Studio error: Permission denied...` (PERMISSION_DENIED/RATE_LIMIT, normal retry/fallback), a cut stream becomes `MALFORMED_RESPONSE` (retried); partial answers are never returned.
  - `grok ask -f` numbers file lines (`  42| code`, prefix declared as not part of the file) by default so cited `path:line` refs are exact; `--no-line-numbers` disables it. `grok code` does NOT number by default (ap snippets are matched verbatim); `--line-numbers` opts in and the prompt says never to copy the prefix.
  - `grok ask --verify-refs DIR` greps every `path:line` in the answer and warns about files/lines that do not exist (existence only, not correctness).
- **Manager as a subagent**: `agents/claude/offload-manager.md` (`grok-offload-manager`, Haiku, gated by
  `grok guard --manager`) runs the orchestrator inside a Claude Code session instead of a separate `claude -p`.
- **Agents load at session start**: `install.sh` copies `agents/claude/*.md` to `~/.claude/agents/`; Claude Code
  sees new agent types only in a new session. Without a restart `subagent_type` is "not found" and no gate is
  attached; do not fall back to an ungated general-purpose agent silently, say so.
- **Never put a task into a double-quoted shell argument** that contains backticks or `$(...)`: the shell runs them.
  (Seen: a prompt mentioning `` `grok code|ask` `` ran `grok code` on $HOME and sent it to the model.) Use
  `--task-file`.
- **`-p` is repeatable**: `-p a -p b` and `-p a b` both pack a and b (before the fix only the last `-p` was packed,
  so the model never saw the file it had to patch: ap "Snippet not found").
- **Permission denied is usually transient** (seen while sibling models were rate-limited; the same model answered a
  minute later): the engine retries the model once after >= 60 s.

## Generation control (never wait silently)

Every model request is watched. While it runs, stderr gets a heartbeat line every 15 s
(`--heartbeat N` / `OFFLOAD_HEARTBEAT_SECONDS`):

```
[grok] waiting: model=gemini-3.1-pro-preview, elapsed=95s, answer_chars=1200 (+300), state=generating
```

`state` = `generating` (output growing or the page shows the Stop indicator / an open answering request),
`idle` (neither), `error` (an error is shown in the UI), `preparing` (before the run: page load, model
selection, typing a long prompt; the line then ends with `phase=...`). Providers other than AI Studio get the
heartbeat (with `phase=`), the status file and the retry rules, but not the page-level stop criteria below.

**Is the generation alive? One command** (needs no login, no browser; routers may run it):

```bash
grok status --runs      # one line per run: pid, model, attempt, state, answer_chars, silent_for, health
# answer_chars = size of the raw streamed response (includes the model's thinking), not of the final answer text
grok status --runs --json
```

`grok status` also closes orphan tabs in the offload browser: tabs whose process was
killed (each tab records its owner pid in `~/.offload-browser/tabs/`). Tabs of live runs are never touched.

```bash
grok watch -i 10        # repeats it until every run has finished
```

The data is `~/.offload-browser/run-<pid>.json` (no secrets; pid, model, attempt, state, answer_chars,
last_progress_ts, per-job list), refreshed every ~5 s by a thread independent of the browser loop;
finished runs stay listed for 10 min and the files are pruned after 24 h.
`health`: `ok`, `finished`/`failed` (final), `DEAD` (the process is gone but the run was active),
`HUNG` (status not refreshed for 30 s: the process is frozen), `SILENT` (no output growth and no generation
indicator for longer than the stall window), `error`. **Exit code 0 = nothing wrong, 2 = some run is
DEAD/HUNG/SILENT/error** (`watch` also stops with 2 as soon as that happens). `state=between` = no request in
flight (retry pause, patch apply, tests).

Stop criteria (AI Studio engine), each ends the attempt at once with the reason on stderr:

- **error in the UI** (banner/toast/model turn: Permission denied, rate limit, quota, Something went wrong,
  Failed to generate...) seen on two consecutive probes: attempt failed with that text, no waiting for the timeout;
- **stall**: no output growth AND no generation indicator for 120 s (`--stall N` / `OFFLOAD_STALL_SECONDS`):
  `STALLED`, a diag bundle is saved, retry in a fresh tab. A model that is visibly "thinking" (Stop indicator)
  is not stalled, however quiet; the heartbeat shows `(+0)` meanwhile;
- the indicator vanished with no output for 20 s: `Empty answer`; sign-in page or a foreign URL: `Session expired`
  (not retried; `login` again);
- **attempt timeout** 900 s (`--attempt-timeout N` / `OFFLOAD_ATTEMPT_TIMEOUT`).

Retries (3 attempts, each next one on the next model of the fallback chain) log
`<model>: attempt N failed (<kind>): <text>; retrying in Ns with <next model>`. Pauses: Permission denied
30 s x N, rate limit 20 s x N, quota 5 s (quota is per model), others 5 s x N. A model that answered
Permission denied gets one more try after >= 60 s (it is usually transient); denied twice, it is not retried. When nothing
works the exit code is non-zero and the **last stderr line** is `DIAG <REASON> <dir>: <text> [attempts: <model>:
<kind>; ...]`.

**Model fallback is never silent.** When the requested model fails and the next one of the chain answers, stderr
says `MODEL FALLBACK: <m> unavailable (<kind>); switching to <next> (requested <req>)` and, on success,
`WARNING: answered by <actual> INSTEAD OF the requested <req>` plus the final line
`result: requested_model=<req> actual_model=<actual> fallback=yes|no`. The status file has `requested_model` /
`actual_model` per job (and on top level), `batch` output lines carry `requested_model`, `actual_model`, `fallback`.
`--no-fallback` (or `OFFLOAD_NO_FALLBACK=1`) makes `-m` strict: no substitute is tried, the command fails with
`requested model <req> unavailable (--no-fallback): <reason>` (same-model retries after a rate limit still happen).

**Saved model answers (`code`).** Every round's raw answer is saved and the path is logged:
`<task-file>.round<N>.ap` (plus `<task-file>.round<N>.afailed.md`, the ap repair briefing, when a patch only
partly applied). Without `--task-file`, or when the task file lies inside the repo (so `--ci` never commits
them), the files go to `~/.offload-browser/rounds/<utc>-<pid>/round<N>.ap`. `code --dry-run` asks the model once,
saves the answer and the extracted patch (`round<N>.patch.ap`), checks it with `ap --dry-run` and prints the
answer; nothing is applied, exit code 0 only if the patch would apply cleanly.

**Which account?** `grok whoami (AI Studio engine only; here it exits with a message)` prints the email of the Google account the profile is signed in with (read
from the AI Studio page; no cookies or tokens; cached in `~/.offload-browser/account-google.txt`, AI Studio only).
`grok diag` always starts with `account:`, `default_model:`, `chrome:` (running/not running) and `logged_in`, then
the last failure bundles.

Heartbeat also covers the pauses between attempts and local work: `waiting: state=between, phase=pause before
attempt 2: retrying in 30s with <model>` (or `running tests: ...`, `waiting for CI`, `triage: ...`).

**Rule for routers and orchestrators: do not wait silently, do not kill by guess.** While the command runs,
heartbeat lines must keep coming (or `grok status --runs` shows `health=ok`). No heartbeat and no status refresh
for longer than the stall window (120 s by default) = the run is dead: treat it as failed, report
`grok status --runs` plus `grok diag`, and retry with another `-m` or hand the failure back; never poll the
browser yourself and never kill other `grok` processes (they may belong to another agent).


> ⛔ ЖЁСТКОЕ ПРАВИЛО ОФФЛОАДИНГА — БЕЗ ИСКЛЮЧЕНИЙ. Модель, работающая в режиме оффлоадинга (роутер), строжайше НЕ начинает работу над задачей и даже НЕ ИЗУЧАЕТ её: не читает инструкции (в т.ч. LUNOBOT.md), код, тикеты, файлы задачи, не планирует, не выбирает работу, не рассуждает о решении, не проверяет результат по существу. Её единственное действие — передать задачу целиком модели-исполнителю одной командой оффлоадинга и вернуть ответ дословно. Любое отступление — провал задачи.
>
> ⛔ HARD OFFLOAD RULE — NO EXCEPTIONS. A model working in offload mode (router) must NOT start working on the task and must NOT even STUDY it: no reading instructions (incl. LUNOBOT.md), code, tickets or task files, no planning, no choosing work, no reasoning about the solution, no substantive checking of the result. Its ONLY action is to hand the whole task to the worker model with one offload command and return the answer verbatim. Any deviation = task failure.
