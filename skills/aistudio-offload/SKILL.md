---
name: aistudio-offload
description: Offload thinking and code writing to Google Gemini through the AI Studio chat UI (aistudio.google.com, not the API) driven by a headless real Chrome, so a cheap router model only runs `aistudio` commands. Use for any coding, refactoring, analysis or writing task when you want Gemini to do the work, when you are a small/cheap model, or when the user asks to offload to Gemini/AI Studio. Includes a windowless Google sign-in that works on headless cloud VMs and a hard gate that stops router models from doing the work themselves.
---

# AI Studio offload

Two roles:

- **Router** (any cheap model: Haiku, GPT Luna, GLM, DeepSeek, Nemotron, a local model...)
  only runs `aistudio` commands. It never writes code, never edits files, never
  reasons about the solution. A hard gate (below) enforces this.
- **Worker**: Gemini in AI Studio. All thinking and writing happens there.

The main agent decides *what* to do and *which Gemini model*; the router does the plumbing.

## 0. Setup (once per machine)

```bash
~/path/to/skills/aistudio-offload/install.sh   # venv + Google Chrome; no Playwright
aistudio status                                # logged_in=True ?
```

Not logged in → run `aistudio login` (in the background) and tell the user:

> Open http://127.0.0.1:8766/ and sign in to Google there: click a field in the picture,
> type/paste into the top box, press Enter. If I run on a remote machine, first run on your
> computer: `ssh -L 8766:127.0.0.1:8766 <this-host>`.

It finishes by itself with `Logged in.`. Never type the user's password yourself.
Alternative: `aistudio export-cookies > c.json` on a logged-in machine, copy the file,
`aistudio import-cookies c.json` on the other (it is a secret; delete it after).

## 1. Code changes — one command does everything

```bash
aistudio code --task-file task.md -C /path/to/repo \
    -p src tests            `# optional: only these paths go into the context` \
    -t "go test ./..."      `# optional: must pass; failures are sent back to Gemini` \
    -m gemini-3.1-pro-preview
```

Packs the repo's tracked files + the [`ap`](https://github.com/unxed/ap) patch spec
into the prompt, Gemini answers with an `ap` patch, it is applied, the test command
runs, and failures (patch or tests) go back to Gemini for up to `-r 4` rounds.
Exit 0 = applied and tests pass. Then review `git diff` and commit.

## 2. Anything else

```bash
aistudio ask "question"                       # answer on stdout
aistudio ask -f a.py -f b.py "review these"   # files inlined into the prompt
aistudio ask -m gemini-2.5-flash -o out.md - < prompt.txt
aistudio batch jobs.jsonl -j 3                # {"id":1,"prompt":"...","files":[...]} per line
```

Parallel: `batch -j N` uses N tabs of one Chrome. Separate `aistudio` processes can also
run at once; `aistudio serve &` keeps one warm Chrome that all of them share
(`aistudio stop` to quit). 1 GB VMs: use `-j 2` at most.

## Models — usually leave it to `auto`

Default is `-m auto`: before the real request, one quick call to `gemini-3.1-flash-lite`
rates the task simple/medium/hard and the worker is picked from that:

| tier   | worker                    | fallback on quota/empty answer |
|--------|---------------------------|--------------------------------|
| simple | `gemini-3.5-flash`        | `gemini-2.5-flash`             |
| medium | `gemini-3.8-flash`        | `gemini-3.5-flash`, `gemini-2.5-flash` |
| hard   | `gemini-3.1-pro-preview`  | `gemini-2.5-pro`, `gemini-3.8-flash`   |

So nobody has to choose a model: not the user, not a root-level router with no main
agent above it. A main agent that knows better passes `-m <id>`. Avoid `gemini-3.6-flash`
(unstable). Tune with `AISTUDIO_MODEL`, `AISTUDIO_TRIAGE_MODEL`.

## 3. Router agents with a hard gate

`agents/claude/gemini-router.md` (Claude Code) and `agents/opencode/gemini-router.md`
(opencode) define a router subagent:

- Claude Code: `tools: Bash` only, plus a `PreToolUse` hook `aistudio guard` that blocks
  every call that is not a single `aistudio ask|code|batch|status|serve ...` command
  (no `;`, `&&`, `|`, `>`, `$(…)`, heredocs, newlines). Install to `~/.claude/agents/`
  (user-level: project-level agent hooks only run after the workspace is trusted).
- opencode: all tools disabled except bash, `permission.bash` allows only `aistudio …`.

Main agent usage: write the task to a file, then delegate:
"Use gemini-router: `aistudio code --task-file /tmp/t.md -C ~/repo -t 'make test' -m gemini-3.1-pro-preview`".

## Troubleshooting

- `Session expired` → `aistudio login` again.
- `Run did not start` / `Empty answer` → quota or safety block: retry later or use another `-m`.
- `Google Chrome not found` → rerun install.sh or set `AISTUDIO_CHROME`.
- State: `~/.aistudio` (`profile/`, `cookies.json` mode 600). Override with `AISTUDIO_HOME`.
