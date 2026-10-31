---
name: grok-offload
description: Offload thinking and code writing to Grok inside X (x.com/i/grok chat, not an API) driven by a headless real Chrome, so a cheap router model only runs `grok` commands. Same interface as aistudio-offload (ask, code with ap patches + tests, batch, login over ssh -L, router hard gate). Use when the user wants Grok as the worker, or as a second free worker next to Gemini.
---

# Grok (X) offload

Same design as the aistudio-offload skill, but a separate, self-contained skill:
this folder carries its own copy of the engine (`offload_core.py`, `cdp.py`, `vendor/ap`).

Roles: a cheap **router** model only runs `grok` commands (hard-gated, see below);
**Grok** does all thinking and writing. Never solve the task yourself.

```bash
./install.sh                     # once; creates ~/.local/bin/grok
grok status || grok login        # sign in to X at http://127.0.0.1:8766/ (ssh -L on VMs)
grok ask "question"              # -m fast (default) | auto | expert
grok code --task-file t.md -C ~/repo -t "go test ./..."   # ap patch, applied + tested
grok batch jobs.jsonl -j 2
```

Notes:
- State lives in `~/.grok-offload` (separate Chrome profile from AI Studio).
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
- **Context size**: the packed context (+task) is limited to 400000 chars (`--max-context N` on `code`/`ask`, or
  `OFFLOAD_MAX_CONTEXT`). Nothing is ever truncated: over the limit the command exits with code 3 and lists the 15
  largest files. `code` on a big repo needs `-p <paths...>`; for `ask` pass fewer `-f`. Every call logs
  `context: N files, M chars`.
- **Diagnostics**: every failed model request saves `~/.offload-browser/diag/<UTC>-<pid>/` (`summary.txt`, `page.txt`,
  `screenshot.jpg`, `alerts.txt`) and prints `DIAG <REASON> <dir>: <message>`. Reasons: STALLED QUOTA RATE_LIMIT
  PERMISSION_DENIED CONTEXT_TOO_LARGE NOT_LOGGED_IN SAFETY EMPTY_ANSWER TIMEOUT UI_CHANGED PATCH_FAILED TESTS_FAILED
  UNKNOWN. `grok diag [N]` prints the last N summaries (routers may run it).
- **Stall watchdog** (AI Studio engine): progress is logged every 30 s; no output growth for 180 s
  (`OFFLOAD_STALL_SECONDS` / `--stall`) = STALLED, a bundle is saved and the request is retried in a fresh tab.
