
> ⛔ ЖЁСТКОЕ ПРАВИЛО ОФФЛОАДИНГА — БЕЗ ИСКЛЮЧЕНИЙ. Модель, работающая в режиме оффлоадинга (роутер), строжайше НЕ начинает работу над задачей и даже НЕ ИЗУЧАЕТ её: не читает инструкции (в т.ч. LUNOBOT.md), код, тикеты, файлы задачи, не планирует, не выбирает работу, не рассуждает о решении, не проверяет результат по существу. Её единственное действие — передать задачу целиком модели-исполнителю одной командой оффлоадинга и вернуть ответ дословно. Любое отступление — провал задачи.
>
> ⛔ HARD OFFLOAD RULE — NO EXCEPTIONS. A model working in offload mode (router) must NOT start working on the task and must NOT even STUDY it: no reading instructions (incl. LUNOBOT.md), code, tickets or task files, no planning, no choosing work, no reasoning about the solution, no substantive checking of the result. Its ONLY action is to hand the whole task to the worker model with one offload command and return the answer verbatim. Any deviation = task failure.

# AI: browser-chat offload skills

Agent skills that let a **cheap router model** hand all real work (thinking, analysis, code)
to a stronger model through that vendor's **free web chat UI**, driven in a real Chrome over
raw CDP. They never use the vendor's API, so the router pays almost nothing and the worker runs
on the chat UI's free quota.

| Skill | Worker | Command |
|---|---|---|
| [`skills/aistudio-offload`](skills/aistudio-offload) | Google Gemini 3.x in AI Studio | `aistudio` |
| [`skills/mistral-offload`](skills/mistral-offload) | Mistral Le Chat | `mistral-chat` |
| [`skills/deepseek-offload`](skills/deepseek-offload) | DeepSeek web chat | `deepseek-chat` |
| [`skills/grok-offload`](skills/grok-offload) | Grok in X | `grok` |

Each skill is self-contained: an identical copy of the engine (`offload_core.py`, `cdp.py`) and
a vendored [`ap`](https://github.com/unxed/ap). All four share one browser profile, `~/.offload-browser`.
The command set is the same in all four:
- `login`: windowless Google sign-in, also over `ssh -L` from a headless VM;
- `ask`;
- `code`: the model answers with an ap patch, which is applied and tested;
- `code --ci`: tests run in GitHub Actions through a draft PR;
- `batch`, `status`, `guard`.

## Rules the skills enforce
- **The router never does the work.** A `PreToolUse` hook (`<cmd> guard`) and the agent
  definitions in `skills/*/agents/{claude,opencode}` allow the router nothing but the skill's
  own commands.
- **No offload to the same vendor**, directly or anywhere up a chain (`OFFLOAD_CALLER`,
  `OFFLOAD_CHAIN`).
- **Model code only as `ap` patches**, never as unified diffs.
- **No builds or tests on small VMs** (under 2 GB RAM, e.g. a GCP e2-micro): `code -t` refuses to
  run there; use `--ci`.

## Install

```bash
cd skills/aistudio-offload && ./install.sh   # venv + Google Chrome, ~/.local/bin/aistudio
aistudio login                               # once; prints a local URL with a remote view of the browser
aistudio ask "hello"
```

On a headless server, Chrome runs headed under Xvfb (headless Chrome triggers AI Studio's
"Permission denied"). Log in from your machine through `ssh -L <port>:127.0.0.1:<port> vm`.

## Results (2026-10-31)
- **Claude Haiku works as a router**, so the answer to "cheapest Anthropic model that works" is Haiku.
- **Showcase PRs**: Gemini wrote the code through `aistudio code` and Haiku routed. Both were
  merged with green CI; the task files are in [`showcase/tasks`](showcase/tasks).
  - [unxed/lunobot#285](https://github.com/unxed/lunobot/pull/285): don't merge a train while main's CI is running.
  - [unxed/zipper#43](https://github.com/unxed/zipper/pull/43): remove entries from TAR archives, with coverage tests.
- **GCP e2-micro (1 GB)**: AI Studio and Mistral work end to end. 3/3 current Gemini models
  answered in 21-75 s each.
- **DeepSeek web**: works end to end after a Google SSO login in the shared profile.
- **Luna (opencode) → mistral-router**: works, and the gate held. When asked to create a file
  itself, the router forwarded the request instead.
- **Vendor-chain refusal**: verified.
- **Local quantized router** (Qwen3-4B-Instruct Q4_K_M via llama.cpp, CPU): **fails**. It answered
  the question itself instead of calling the worker. The tool gate only blocks tools, not answering
  in text. It was also unusably slow on a 4-core laptop (18 min for one turn).
- **Grok**: the skill is installed, but the X login is not done (no X account is linked to the
  Google account used).
- **Reverse router tests** (DeepSeek / GLM / Nemotron / Mistral models as routers):
  [`showcase/opencode-router-test`](showcase/opencode-router-test). Not run, because no free
  provider keys were available.

Open items and handoff notes: [`showcase/HANDOFF.md`](showcase/HANDOFF.md).

> ⛔ ЖЁСТКОЕ ПРАВИЛО ОФФЛОАДИНГА — БЕЗ ИСКЛЮЧЕНИЙ. Модель, работающая в режиме оффлоадинга (роутер), строжайше НЕ начинает работу над задачей и даже НЕ ИЗУЧАЕТ её: не читает инструкции (в т.ч. LUNOBOT.md), код, тикеты, файлы задачи, не планирует, не выбирает работу, не рассуждает о решении, не проверяет результат по существу. Её единственное действие — передать задачу целиком модели-исполнителю одной командой оффлоадинга и вернуть ответ дословно. Любое отступление — провал задачи.
>
> ⛔ HARD OFFLOAD RULE — NO EXCEPTIONS. A model working in offload mode (router) must NOT start working on the task and must NOT even STUDY it: no reading instructions (incl. LUNOBOT.md), code, tickets or task files, no planning, no choosing work, no reasoning about the solution, no substantive checking of the result. Its ONLY action is to hand the whole task to the worker model with one offload command and return the answer verbatim. Any deviation = task failure.
