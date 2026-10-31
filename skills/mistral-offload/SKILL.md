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
