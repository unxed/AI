---
name: aistudio-offload
description: Offload thinking and code writing to Google Gemini through the AI Studio chat UI (aistudio.google.com, not the API) driven by a headless real Chrome, so a cheap router model only runs `aistudio` commands. Code comes back ONLY as an `ap` patch (https://github.com/unxed/ap), never as a unified diff. Use for any coding, refactoring, analysis or writing task when you want Gemini to do the work, when you are a small/cheap model, or when the user asks to offload to Gemini/AI Studio. Includes a windowless Google sign-in that works on headless cloud VMs and a hard gate that stops router models from doing the work themselves.
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
runs, and failures (patch or tests) go back to Gemini for up to `-r 3` rounds (the first
answer + 2 retries). Exit 0 = applied and tests pass. Then read the result (`git diff` is
fine for *reading*, never as an answer format) and commit.

**Small cloud VMs (< 2 GB RAM, e.g. GCP e2-micro): never build or test locally.** Use
`--ci` instead of `-t`: each round's patch is committed to a branch (`--ci-branch`,
default `offload/<timestamp>`), pushed, a **draft PR** is opened against `--ci-base`
(default `main`; most workflows run on `pull_request`) and the GitHub Actions runs of
that commit are awaited; failed-step logs go back to the model. Needs `gh auth login`.
`code -t` refuses to run on such machines (override: `OFFLOAD_ALLOW_LOCAL_BUILD=1`).

```bash
aistudio code --task-file task.md -C ~/repo --ci --ci-branch fix/issue-42
```

## Patch format: `ap` only, unified diff is forbidden (hard rule)

Models miscount the line numbers in `@@ -a,b +c,d @@` headers, so diffs fail constantly.
Every task that makes a model change code - through `aistudio code`, through `ask`, or by
hand in the AI Studio tab / in parallel browser streams - uses the `ap` format and nothing else.
Never write "reply with a ```diff block", never use `git apply` (`--check`, `--recount`...)
for model output. `aistudio code` rejects a diff answer and asks again.

**Tool**: `ap` (wrapper installed by `install.sh` to `~/.local/bin/ap`, running the vendored
`vendor/ap.py`; no pip/sudo; a copy of the spec is `vendor/ap.md`). Check: `ap --version`.

**Prompt fragment** (for hand-made prompts; attach/inline `vendor/ap.md` as the spec):

> Answer ONLY with one patch in the `ap` format described in the attached spec, inside a single
> ```ap block (random 8-hex patch ID, `AP 3.2` header, FILE / REPLACE / INSERT_AFTER ... with
> `snippet` / `content` copied verbatim from the files I gave you). A unified diff, `git diff`,
> `--- a/ +++ b/ @@` hunks or whole-file dumps are FORBIDDEN. No explanations outside the block.

**Applying** (save the block as e.g. `afix.ap` in the repo root):

```bash
ap afix.ap --dir /path/to/repo            # apply
ap afix.ap --dir /path/to/repo --dry-run  # show the planned changes, write nothing
```

Rely on the patcher's own self-healing and do not add workarounds on top of it. Run it in the
default *tolerant* mode (do NOT pass `-s`): it fuzzily matches locators, forgives a missing header
or ID drift, applies every modification that resolves and skips ones already present. Exit 0 =
everything applied. Exit 2 = **partly applied**: the failed modifications are in `afailed.ap` and a
repair briefing for the model in `afailed.md` (error codes, closest existing text, current file
contents). Send the whole `afailed.md` to the same chat, ask for a NEW `ap` patch with only the
fixes (not a resend of the applied ones), delete `afailed.ap`/`afailed.md` (the patcher refuses to
run while they exist), apply again. At most 2 such retries, then report the failure. `aistudio code`
does all of this automatically. Afterwards always run the project's checks (`php -l`, tests, build).

**Parallel streams in the browser** (one AI Studio tab per stream, no `aistudio` CLI): each stream
gets the task + file contents + the prompt fragment above, saves the answer as its own `.ap` file,
and the integrator applies the files one by one with `ap`; a stream whose patch only partly applies
is repaired with its `afailed.md` as described. Distinct streams must touch distinct files or at
least distinct snippets.

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

## Vendor chain (hard rule)

A vendor never offloads to itself, directly or anywhere up a chain (no Gemini planning work
for Gemini, no Haiku→Gemini→…→Gemini). Every ask/code/batch call needs `OFFLOAD_CALLER=<model>`
(auto-detected as `anthropic` inside Claude Code) and honours `OFFLOAD_CHAIN` (e.g.
`anthropic>google`): if the worker's vendor is already in it, the call is refused. The extended
chain is exported to child processes (e.g. the `-t` test command) and printed on stderr — pass
it as `OFFLOAD_CHAIN=...` to any sub-task derived from the answer.

## Troubleshooting

- `Session expired` → `aistudio login` again.
- `afailed.ap exists ...` from `ap` → delete `afailed.ap`/`afailed.md` and rerun.
- `Run did not start` / `Empty answer` → quota or safety block: retry later or use another `-m`.
- `Google Chrome not found` → rerun install.sh or set `AISTUDIO_CHROME`.
- State: `~/.aistudio` (`profile/`, `cookies.json` mode 600). Override with `AISTUDIO_HOME`.
