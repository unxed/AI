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
- **Stall watchdog** (AI Studio engine): progress is logged every 30 s; no output growth for 180 s
  (`OFFLOAD_STALL_SECONDS` / `--stall`) = STALLED, a bundle is saved and the request is retried in a fresh tab.
