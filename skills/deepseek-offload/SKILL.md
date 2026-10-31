---
name: deepseek-offload
description: Offload thinking and code writing to DeepSeek's free web chat (chat.deepseek.com, not the API) driven by a headless real Chrome, so a cheap router model only runs `deepseek-chat` commands. Good for simple/medium tasks with near-unlimited use. Same interface as aistudio-offload (ask, code with ap patches + tests, batch, windowless login over ssh -L, router hard gate, vendor-chain guard).
---

# DeepSeek (web chat) offload

Separate, self-contained skill (own copy of the engine: `offload_core.py`, `cdp.py`,
`vendor/ap`). Roles: a cheap **router** runs `deepseek-chat` commands only (hard gate);
**DeepSeek** does all thinking and writing. Never solve the task yourself.

```bash
./install.sh                         # once: venv + Google Chrome, ~/.local/bin/deepseek-chat
deepseek-chat status || deepseek-chat login   # http://127.0.0.1:8766/ ("Log in with Google" works)
deepseek-chat ask "question"         # -m chat (default) | think (DeepThink reasoning)
deepseek-chat code --task-file t.md -C ~/repo -t "go test ./..."   # ap patch, applied + tested
deepseek-chat batch jobs.jsonl -j 2
```

- Browser profile is shared by all *-offload skills (`~/.offload-browser`): if you are signed
  in to Google there (e.g. via `aistudio login`), DeepSeek's "Log in with Google" is one click.
- Web search is switched off, DeepThink only with `-m think`. The answer is read from the
  chat history API (RESPONSE fragments), so it is raw markdown with fences; reasoning is skipped.
- Prompts over ~50k characters (e.g. `code` with a codebase) are attached as a `.txt` file.

**Small cloud VMs (< 2 GB RAM, e.g. GCP e2-micro): never build or test locally.** Use
`--ci` instead of `-t`: each round's patch is committed to a branch (`--ci-branch`,
default `offload/<timestamp>`), pushed, a **draft PR** is opened against `--ci-base`
(default `main`; most workflows run on `pull_request`) and the GitHub Actions runs of
that commit are awaited; failed-step logs go back to the model. Needs `gh auth login`.
`code -t` refuses to run on such machines (override: `OFFLOAD_ALLOW_LOCAL_BUILD=1`).

```bash
deepseek-chat code --task-file task.md -C ~/repo --ci --ci-branch fix/issue-42
```

## Vendor chain (hard rule)

A vendor never offloads to itself, directly or anywhere up a chain. Every call needs
`OFFLOAD_CALLER=<model>` (auto-detected inside Claude Code) and honours `OFFLOAD_CHAIN`
(e.g. `anthropic>google`): if `deepseek` is already in it the call is refused. The extended
chain is exported to child processes and printed on stderr — pass it to any sub-task you
derive from the answer.

## Router with a hard gate

`agents/claude/deepseek-router.md` (Claude Code: Bash only + `PreToolUse` hook
`deepseek-chat guard`, install to `~/.claude/agents/`) and `agents/opencode/deepseek-router.md`
(bash allowed only for `deepseek-chat …`).

## Manager gate, context size, diagnostics

- **Web UI only (hard rule)**: DeepSeek chat is reached only through the browser UI driven over CDP. Never add or use an API path; never use its API, API keys or SDKs.
- **The main agent never does the work itself** when offloading: no code, analysis, triage, texts or markdown
  edits of its own. Write a task file and hand it to the router subagent.
- **Manager gate**: make a small orchestrator model unable to cheat with the PreToolUse hook `deepseek-chat guard --manager`
  (blocks Edit/MultiEdit/NotebookEdit, Write except `task*.md`/`*.task.md`/`tasks/`, and inline code or file writes in
  Bash: `python3 -c`, heredocs, `sed -i`, `perl -e/-i`, `tee`, `> file`, `git apply`/`patch`/`ap`, `gh --body "..."`):
  `claude -p --settings '{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"deepseek-chat guard --manager"}]}]}}'`
- **Context size**: the packed context (+task) is limited to 400000 chars (`--max-context N` on `code`/`ask`, or
  `OFFLOAD_MAX_CONTEXT`). Nothing is ever truncated: over the limit the command exits with code 3 and lists the 15
  largest files. `code` on a big repo needs `-p <paths...>`; for `ask` pass fewer `-f`. Every call logs
  `context: N files, M chars`.
- **Diagnostics**: every failed model request saves `~/.offload-browser/diag/<UTC>-<pid>/` (`summary.txt`, `page.txt`,
  `screenshot.jpg`, `alerts.txt`) and prints `DIAG <REASON> <dir>: <message>`. Reasons: STALLED QUOTA RATE_LIMIT
  PERMISSION_DENIED CONTEXT_TOO_LARGE NOT_LOGGED_IN SAFETY EMPTY_ANSWER TIMEOUT UI_CHANGED PATCH_FAILED TESTS_FAILED
  UNKNOWN. `deepseek-chat diag [N]` prints the last N summaries (routers may run it).

## Generation control (never wait silently)

Every model request is watched. While it runs, stderr gets a heartbeat line every 15 s
(`--heartbeat N` / `OFFLOAD_HEARTBEAT_SECONDS`):

```
[deepseek-chat] waiting: model=gemini-3.1-pro-preview, elapsed=95s, answer_chars=1200 (+300), state=generating
```

`state` = `generating` (output growing or the page shows the Stop indicator / an open answering request),
`idle` (neither), `error` (an error is shown in the UI), `preparing` (before the run: page load, model
selection, typing a long prompt; the line then ends with `phase=...`). Providers other than AI Studio get the
heartbeat (with `phase=`), the status file and the retry rules, but not the page-level stop criteria below.

**Is the generation alive? One command** (needs no login, no browser; routers may run it):

```bash
deepseek-chat status --runs      # one line per run: pid, model, attempt, state, answer_chars, silent_for, health
deepseek-chat status --runs --json
deepseek-chat watch -i 10        # repeats it until every run has finished
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
Permission denied is never tried again: if no other model is left the command stops at once. When nothing
works the exit code is non-zero and the **last stderr line** is `DIAG <REASON> <dir>: <text> [attempts: <model>:
<kind>; ...]`.

**Rule for routers and orchestrators: do not wait silently, do not kill by guess.** While the command runs,
heartbeat lines must keep coming (or `deepseek-chat status --runs` shows `health=ok`). No heartbeat and no status refresh
for longer than the stall window (120 s by default) = the run is dead: treat it as failed, report
`deepseek-chat status --runs` plus `deepseek-chat diag`, and retry with another `-m` or hand the failure back; never poll the
browser yourself and never kill other `deepseek-chat` processes (they may belong to another agent).

