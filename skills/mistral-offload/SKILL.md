---
name: mistral-offload
description: Offload thinking and code writing to Mistral's free web chat Le Chat (chat.mistral.ai, not the API) driven by a headless real Chrome, so a cheap router model only runs `mistral-chat` commands. Good for simple/medium tasks with near-unlimited use. Same interface as aistudio-offload (ask, code with ap patches + tests, batch, windowless login over ssh -L, router hard gate, vendor-chain guard).
---

# Mistral Le Chat offload

Separate, self-contained skill (own copy of the engine: `offload_core.py`, `cdp.py`,
`vendor/ap`). Roles: a cheap **router** runs `mistral-chat` commands only (hard gate);
**Mistral** does all thinking and writing. Never solve the task yourself.

```bash
./install.sh                         # once: venv + Google Chrome, ~/.local/bin/mistral-chat
mistral-chat status || mistral-chat login   # http://127.0.0.1:8766/ ("Continue with Google" works)
mistral-chat ask "question"          # -m fast (default) | think (reasoning mode)
mistral-chat code --task-file t.md -C ~/repo -t "go test ./..."   # ap patch, applied + tested
mistral-chat batch jobs.jsonl -j 2
```

- Browser profile is shared by all *-offload skills (`~/.offload-browser`): if you are signed
  in to Google there (e.g. via `aistudio login`), Mistral's "Continue with Google" is one click.
- Every request runs in a **temporary (incognito) chat**, so nothing piles up in your history.
- The answer is read from the `/api/chat` stream (JSON patches of the assistant message), so
  it is raw markdown with fences.
- Long prompts (e.g. `code` with a codebase) are attached as a `.txt` file.

**Small cloud VMs (< 2 GB RAM, e.g. GCP e2-micro): never build or test locally.** Use
`--ci` instead of `-t`: each round's patch is committed to a branch (`--ci-branch`,
default `offload/<timestamp>`), pushed, a **draft PR** is opened against `--ci-base`
(default `main`; most workflows run on `pull_request`) and the GitHub Actions runs of
that commit are awaited; failed-step logs go back to the model. Needs `gh auth login`.
`code -t` refuses to run on such machines (override: `OFFLOAD_ALLOW_LOCAL_BUILD=1`).

```bash
mistral-chat code --task-file task.md -C ~/repo --ci --ci-branch fix/issue-42
```

## Vendor chain (hard rule)

A vendor never offloads to itself, directly or anywhere up a chain. Every call needs
`OFFLOAD_CALLER=<model>` (auto-detected inside Claude Code) and honours `OFFLOAD_CHAIN`
(e.g. `anthropic>google`): if `mistral` is already in it the call is refused. So a Mistral
model (Devstral, Magistral, ...) as router cannot use this skill, but can use the
aistudio/deepseek/grok ones. The extended chain is exported to child processes and printed
on stderr: pass it to any sub-task you derive from the answer.

## Router with a hard gate

`agents/claude/mistral-router.md` (Claude Code: Bash only + `PreToolUse` hook
`mistral-chat guard`, install to `~/.claude/agents/`) and `agents/opencode/mistral-router.md`
(bash allowed only for `mistral-chat …`).

## Manager gate, context size, diagnostics

- **Web UI only (hard rule)**: Le Chat (chat.mistral.ai) is reached only through the browser UI driven over CDP. Never add or use an API path; never use its API, API keys or SDKs.
- **The main agent never does the work itself** when offloading: no code, analysis, triage, texts or markdown
  edits of its own. Write a task file and hand it to the router subagent.
- **Manager gate**: make a small orchestrator model unable to cheat with the PreToolUse hook `mistral-chat guard --manager`
  (blocks Edit/MultiEdit/NotebookEdit, Write except `task*.md`/`*.task.md`/`tasks/`, and inline code or file writes in
  Bash: `python3 -c`, heredocs, `sed -i`, `perl -e/-i`, `tee`, `> file`, `git apply`/`patch`/`ap`, `gh --body "..."`):
  `claude -p --settings '{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"mistral-chat guard --manager"}]}]}}'`
- **Context size**: the packed context (+task) is limited to 400000 chars (`--max-context N` on `code`/`ask`, or
  `OFFLOAD_MAX_CONTEXT`). Nothing is ever truncated: over the limit the command exits with code 3 and lists the 15
  largest files. `code` on a big repo needs `-p <paths...>`; for `ask` pass fewer `-f`. Every call logs
  `context: N files, M chars`.
- **Diagnostics**: every failed model request saves `~/.offload-browser/diag/<UTC>-<pid>/` (`summary.txt`, `page.txt`,
  `screenshot.jpg`, `alerts.txt`) and prints `DIAG <REASON> <dir>: <message>`. Reasons: STALLED QUOTA RATE_LIMIT
  PERMISSION_DENIED CONTEXT_TOO_LARGE NOT_LOGGED_IN SAFETY EMPTY_ANSWER TIMEOUT UI_CHANGED PATCH_FAILED TESTS_FAILED
  UNKNOWN. `mistral-chat diag [N]` prints the last N summaries (routers may run it).
- **Stall watchdog** (AI Studio engine): progress is logged every 30 s; no output growth for 180 s
  (`OFFLOAD_STALL_SECONDS` / `--stall`) = STALLED, a bundle is saved and the request is retried in a fresh tab.
