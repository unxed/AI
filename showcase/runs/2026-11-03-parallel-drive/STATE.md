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
- Owner (23:05): Claude will be installed on the VM, but running the router through opencode is still very useful, including locally, to save Haiku tokens. Keep the opencode+headless path.
- Session ran out of tokens at ~23:05. WIP of the still-running routers was snapshotted to wip/2026-11-03-* branches (non-disruptive commit-tree push). The routers may still finish and open their own PRs (offload/headless-runner, skills/fail-fast-everywhere).
- DEEPSEEK STOPPED 23:05 at the 40-min deadline (~33 actions, no edits, no PR). Findings: @playwright/mcp needs Node >=20, this machine has 18.19.1 (0.0.30 declares >=18, but its playwright dep needs >=20). Opencode 2.1.4: neither env OPENCODE_CONFIG_CONTENT with "mcp" nor with mcp.servers registered ("No MCP servers configured"). `opencode mcp add` writes ./opencode.json with mcp.servers.playwright; untested whether `mcp list` reads that project file. Lesson: the model re-read the same SKILL.md chunks ~10 times; a 40-min deadline is too short for design work. Next: give the worker these findings up front, raise the deadline, split the task (1: opencode MCP config format; 2: runner rewrite).
- verbatim-relay class fix pushed (Arena/DeepSeek/Qwen routers mistyped or paraphrased outputs).
- Z.AI STOPPED 23:07: no reply to run#3 within 8 min ('Thinking...', text unchanged). May be the same false 'no reply' (text-length detection, fixed in 8b62216 after this router had already read the skill). No changes in luno-zai. Only Qwen is still running.
- Z.ai lessons: (1) multi-line results can't be typed (Enter sends the message) → form_input / insertText; partly covered by the verbatim rule in 7001c5f. (2) Keeping only the last 3000 chars loses the beginning of a combined command's output → TODO: tell the model to issue one short command per action, or cut as head+tail. (3) GLM-5.3-Flash takes 2-4 min per turn, too slow for the 40-min/60-action budget. Z.ai attach works (LUNOBOT.md and ap.md chips).
- Owner note: they usually attach ap.md + the needed repo files as ONE file built with ~/dev/ap/tools/combine.py. TODO: consider it for the skills (delivery of a local file without retyping is the open question).
- QWEN STOPPED 23:08: Send stopped submitting (ref click, coordinate click and Return all failed; composer kept its text), deadline near, no edits. Possibly a Qwen rate limit or composer state. Fail-fast task for unxed/AI NOT done; redo it in a new session (maybe with aistudio/deepseek). ALL 5 runs are now finished.
- 9ddc1df pushed: drive mode attaches whole files (the caller names them), the model requests files via attach instead of sed chunks, REPEAT guard for identical actions. luno-task.md template updated to match.

## 2026-11-04
- go2dos#70 (SSE2 stand, DeepSeek) STOPPED: about 50 actions of reading, then an ap patch with broken YAML indentation, then a `write` whose JSON came out garbled (Unicode italic letters, broken quotes — page markdown rendering). Nothing was pushed. The broken file is saved as offload/hx-far-run.broken.yml and the clone was reverted. Classes: DSML format (17e8ce6), reading loop with overlapping ranges (04fdf16). Open: no syntax feedback after ap/write; large `write` content gets mangled.
- f4#2216 (fix and merge the calendar PR, DeepSeek) still running.
- LUNOBOT 33aee9e: contributor-friendly rule in caps (§ 6 and the merge module).
- HX#75: polite reminder about PR #76 posted (owner approved).
- f4#2230 was auto-closed by `Fixes` in #2252; reopen pending the owner's decision.
- 09:24 owner: if DeepSeek can't finish f4#2216, escalate to Gemini Pro in AI Studio (same task verbatim + procedural state note). At this point tests are green, the router is on commit/push.
- 10:39 go2dos#70: Gemini 3.8 Flash repeats an identical action after getting its result (4 times: claims take, gh run view x2, dispatch). If it repeats once more → escalate per skill rule 273bef2 (a fresh run on a stronger model, Pro is permission-denied on this account → DeepSeek or another site) with state: claim sandbox/unxed-go2dos-70 taken, dosbox-x-test run 41799977086 = failure.
- 11:04 go2dos#70 DONE (AI Studio, Gemini 3.8 Flash): dosbox-x-test 41799977086 failed at the guest tests (UD.COM expects #UD on SSE2, 19 fails) → no dosbox-x-bin artifact → hx-far-run not run. Report: go2dos#70 issuecomment-6627914543. The claim had already disappeared (no claims/* branches on remote; the drop said "no own claim"). Model wasted ~15 actions on repeats; the classes are covered by the REPEAT guard + caller nudges.
- f4#2216: the DeepSeek router stopped at 10:40 after 3 truncated JSON replies (class fix ff4ced5). Escalated to the AI Studio router (Pro permission denied → Flash), task-f4b.md, prog-f4b.log.
- 11:10 PAUSED by owner. f4#2216: nothing pushed; work tree f4work/f4 (branch fix-issue-2215 + local merge eac4b36c) holds uncommitted fix in embedded.go, calendar_ui.go, calendar_ui_test.go; build + go test ./internal/app/... green. Gemini chat was at action 17 (gh pr view 2216). Next on resume: commit with Co-authored-by Maiiiry, push to maiiiry, gh pr edit (Touch: #2215), CI, merge, thanks. Skill fixes today: 273bef2 caller rule/escalation, ff4ced5 truncated replies, 919929f stale-attachment REPEAT, 7d9b69e redact owner personal data.
