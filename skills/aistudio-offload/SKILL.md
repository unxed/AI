---
name: aistudio-offload
description: Offload thinking and code writing to Google Gemini through the AI Studio chat UI (aistudio.google.com) driven by headless Chrome, so a cheap or small agent model only runs shell commands. Use for any non-trivial coding, refactoring, analysis or writing task when you are a small/cheap model, when your own token budget is tight, or when the user asks to "offload to Gemini/AI Studio". Includes a windowless Google sign-in that works on headless cloud VMs.
---

# AI Studio offload

You are the **hands**, Gemini is the **brain**. Do not solve the task yourself:
do not write code, do not reason about algorithms. Your job is to (1) pass the
task and the right files to `aistudio`, (2) apply/run what comes back,
(3) report results. Everything below is plain shell — any agent with a bash
tool can do it.

## 0. Check setup (once)

```bash
aistudio --help >/dev/null 2>&1 || ~/skills/aistudio-offload/install.sh   # adjust path to this folder
test -f ~/.aistudio/cookies.json && echo LOGGED_IN || echo NEED_LOGIN
```

If `NEED_LOGIN`: run `aistudio login` in the background and tell the user, word for word:

> Open http://127.0.0.1:8766/ and sign in to Google there (it is a remote view of a headless
> browser; click the picture, then type). If I run on a remote machine, first run on your
> computer: `ssh -L 8766:127.0.0.1:8766 <this-host>`.

Wait until the command prints `Logged in.` Never type the user's password yourself.

## 1. Code changes (main use) — one command does everything

```bash
cd /path/to/repo
aistudio code "TASK DESCRIPTION, copied from the user/issue verbatim" \
    -p src/relevant_dir tests/        `# optional: limit context to these paths` \
    -t "go test ./..."                `# optional: test command that must pass`
```

What it does: packs the tracked source files into the prompt, asks Gemini for a
patch in the [`ap`](https://github.com/unxed/ap) format, applies it, runs the
test command, and on failure sends the error back and retries (`-r 4` rounds).
Exit code 0 = patch applied (and tests pass). Then just `git diff` and commit.

- Big repo? Pass `-p` with only the directories that matter (keep context < ~2 MB).
- Put long task text into a file: `aistudio code - < task.md`.
- If it prints `FAILED after N rounds`: run it again with a more specific task
  (add the error text), or a stronger model: `-m gemini-3.1-pro-preview`.

## 2. Questions, reviews, plans, any text

```bash
aistudio ask "question"                       # answer on stdout
aistudio ask -f a.py -f b.py "review these"   # files are inlined into the prompt
aistudio ask -o plan.md - < prompt.txt        # long prompt from stdin, answer to file
```

## 3. Parallel work

Start the daemon once; then every `aistudio` call reuses one warm browser and
runs in its own tab, so you can launch several in the background (`&`).

```bash
aistudio serve --tabs 3 &          # 3 parallel chats; ~1 GB RAM VM: use --tabs 2
aistudio batch jobs.jsonl -j 3     # {"id":1,"prompt":"...","files":["a.py"]} per line
```

## Models

Default `gemini-3.8-flash` (fast, strong). `-m <id>` to change: `gemini-3.1-pro-preview`
(hardest tasks), `gemini-3.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash` (simple
tasks / when other quotas run out). Avoid `gemini-3.6-flash` (unstable).

## Troubleshooting

- `Session expired` / redirected to accounts.google.com → `aistudio login` again.
- `Run did not start (quota?...)` → wait a minute or switch model with `-m`.
- Low-RAM VM (1 GB): keep ≥1 GB swap, use `--tabs 1-2`.
- Files: state in `~/.aistudio` (`cookies.json` is a secret, mode 600). Override with `AISTUDIO_HOME`.
