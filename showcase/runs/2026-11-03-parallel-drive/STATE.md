# Offload test runs — state 2026-11-03 ~22:55

Folder: this `offload/` dir. Routers are Haiku subagents, each in its own built-in-browser tab, drive mode.
Each router appends to its progress file. Watch the progress files (stall >4 min = failure, intervene).

| Worker | Task file | Work dir | Progress | Goal |
|---|---|---|---|---|
| DeepSeek | hl-task.md | hlwork/ (lunobot + AI clones) | hl-progress.log | headless-browser runner: rework lunobot/runners/lunobot-round-opencode-gemini.sh; PR offload/headless-runner (+ AI PR if skills touched); no merge |
| Qwen | task-qwen.md | ai-qwen/ | prog-qwen.log | fail fast as general rule in all 9 SKILL.md; PR skills/fail-fast-everywhere in unxed/AI; no merge |
| Z.ai | task-zai.md | luno-zai/ | prog-zai.log | one small Lunobot task (claim/work/report) |
| Cerebras | task-cerebras.md | luno-cerebras/ | prog-cerebras.log | same (2nd attempt after skill fixes) |
| Arena (kimi-k3) | task-arena.md | luno-arena/ | prog-arena.log | same |

Done earlier today: DeepSeek closed unxed/lunobot#262 (fix already merged in PR #285) with report.

## Skill fixes pushed to unxed/AI main today
- 89d0a66: attach fallback in all 9 skills (site rejects text attachments → read via run / curl raw URL; reply `attach unsupported: read via run`). Cerebras, Arena: png/jpg only. Qwen: file input present but files=0.
- ec98635: ap spec always attached, never pasted; run/curl fallback; non-drive code tasks → drive mode.
- 13717b2: Arena only for tasks with all-public data; refuse non-public up front; never click accept.

## Known/open
- Qwen and DeepSeek PRs edit all 9 SKILL.md on branches cut before these fixes → expect merge conflicts; resolve on review.
- Hidden built-in pane: first click fails; routers tabs_select their tab (contention with parallel routers). Not fixed yet.
- Arena router once paraphrased a command output, then retyped verbatim. If repeated: add "outputs verbatim only" rule.
- After all finish: verify on GitHub (claims, comments, PRs), review PR diffs, then report to owner.
- Pending later: nothing else approved; Grok login / FreeLLMAPI tails declined.
- ARENA STOPPED 22:52: after the 2nd reply arena.ai switched the chat to an anonymous side-by-side battle ("Which response do you prefer?", Ответ A/B), even though kimi-k3 had been picked via "Mention a model". The router stopped correctly and did not vote. TODO: fix the arena skill so it opens explicit Direct/single-model mode (not "mention") and checks after every reply that there is no A/B; on A/B → PROBLEM + stop. Arena also rejects text attachments (fallback works). No changes were made in luno-arena.
- Z.ai router falsely judged 'no reply' by unchanged page text length; reply was there (seen via screenshot). TODO class fix: detect reply via last code block textContent / marker, not page text length.
- Hidden pane: javascript_tool waits time out at ~45s → TODO class fix in all skills: poll with short waits (≤30s per call, repeat), never one long JS await.
- CEREBRAS STOPPED 22:59: "The server encountered an error" twice. Before that the model (Qwen 3.8 27B) read all 796 lines of LUNOBOT.md in 10 sed actions, which probably overflowed its context. TODO class fix: the attach-fallback line should say "read selectively: grep -n '^## ' first, then only the sections you need". Also: truncate outputs by characters, not bytes (Cyrillic). No changes in luno-cerebras.
- c4685f6 pushed: attach fallback reads selectively (headers first) + truncate by chars not bytes (both class fixes, all 9 skills).
- 8b62216 pushed: reply detection by marker/action block + JS waits ≤30s (class fixes for the Z.ai false 'no reply' and the Qwen hidden-pane timeout). Still open: Arena single-model mode; tabs_select contention.
