---
name: grok-offload
description: Offload thinking and code writing to Grok inside X (x.com/i/grok chat, not an API) driven by a headless real Chrome, so a cheap router model only runs `grok` commands. Same interface as aistudio-offload (ask, code with ap patches + tests, batch, login over ssh -L, router hard gate). Use when the user wants Grok as the worker, or as a second free worker next to Gemini.
---

# Grok (X) offload

Twin of [aistudio-offload](../aistudio-offload/SKILL.md): identical commands, flags and
router rules — only the worker differs. Read that SKILL.md; replace `aistudio` with `grok`.
Requires the `aistudio-offload` folder next to this one.

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
- Router gate: the same `aistudio guard` hook also allows single `grok ...` commands.
