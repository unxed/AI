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
