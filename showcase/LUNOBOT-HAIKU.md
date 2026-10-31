# Lunobot on Haiku + Gemini offload: status and handoff (2026-10-31, ~21:40 UTC)

Owner's goal: run Lunobot (unxed/lunobot) as **Claude Code subagents inside the owner's session** (not
separate runner processes), each on Claude Haiku, offloading ALL substantive work to Gemini (AI Studio
web UI via `aistudio`, see `../skills/aistudio-offload`) and other vendors' web chats. Main session (Opus)
spends as few tokens as possible. Lunobot-1 = strong/new Gemini (3.1-pro-preview, 3.8-flash),
Lunobot-2 = weaker (3.5-flash-lite) + Mistral. Loop: one round, then a 15 min pause.
**Current mode (owner, debugging): ONE worker, tasks one by one, strict status tracking with timeouts,
full debug info. Goal now is to polish Haiku + offload, not throughput.**

## History
- 14:06-19:02 UTC: Lunobot ran via local runner scripts (`lunobot-round-haiku.sh`, claude -p). The owner
  did NOT ask for runners; removed: unxed/lunobot commit 7c83216 reverted in 8982d77, local files deleted.
- Incident 14:06: backticks in the runner prompt made bash run `aistudio code` on $HOME; ~2.3 MB of home
  files went into two AI Studio chats. Owner should delete those chats / rotate secrets if any.
- Gemini produced nothing that landed in repos in those rounds (all offloaded steps failed, see below).

## Failures found and fixed in the skill (all pushed to unxed/AI)
| Problem (evidence) | Fix |
|---|---|
| Haiku manager did the work itself (triage rows, REFLECTION, etc.) | `guard --manager` gate (07f3e44), `agents/claude/offload-manager.md` (7a7cd6a) |
| Whole repo/dir sent: 41 M / 2.8 M chars, silent truncation at 3 M | 400k limit, exit 3 CONTEXT_TOO_LARGE + largest files (07f3e44) |
| Failures without reasons | diag bundles `~/.offload-browser/diag/`, reason codes, `aistudio diag` (07f3e44) |
| Generation hangs unnoticed | progress log + stall watchdog STALLED -> retry (07f3e44; extended by 961f5ec) |
| flash "Permission denied" while pros rate-limited; OK a minute later | one retry after 60 s (1cc4c72) |
| `-p a -p b -p c` packed only `c` -> ap "Snippet not found" x3 on TRIAGE.md | `nargs="+", action="extend"` (a410799) |
| New agent types load only at session start; quoting pitfalls | install.sh copies agents; SKILL.md notes (7a7cd6a) |

## Results (one-worker mode, gated `lunobot-haiku` subagents in the owner's session)
- f4 triage of 912, 1980, 2226, 2228, 2230 by Gemini (3.8-flash): unxed/lunobot dcc61b7 (pushed by Opus, the
  worker stopped because the triage gate was red for older tickets).
- unxed/vtui#256 review comment by gemini-3.5-flash-lite, fully autonomous (Лунобот-2):
  https://github.com/unxed/vtui/pull/256#issuecomment-6548659801
- D-05 (account-216, unxed/f4#2162) analysis by gemini-3.8-flash recorded in status/2162.md: unxed/lunobot 092f7ce.
  ~10 of 17 file:line refs were wrong (correction block added). OWNER_QUEUE state still says "взял в работу".
- Signature rule for offloading (router + worker model): unxed/lunobot b2b7357.

## More skill fixes pushed
| Problem | Fix |
|---|---|
| untracked `-p` dir silently not packed; quota on whole chain -> exit after 11 min | c6c476b |
| manager gate blocked relative redirects into the work dir (no debug log written) | 0969655 |

- goWidgets#43 triage: unxed/lunobot 24da9a4 (Gemini rated it; row written by tools/triage_touch.py because both
  Gemini patches glued the row to the last line of a file without trailing newline -> fixed in ap).
- account-216 state line fixed fully autonomously via aistudio code (7 s, 1 file changed, no DIAG): 938dacf.

| Problem | Fix |
|---|---|
| `code` "success" with unchanged file; error chunk broke JSON; wrong file:line refs | 4b1fd23 (PATCH_NOOP, robust stream parse, line-numbered ask, --verify-refs) |
| ap INSERT_AFTER at EOF without newline glued lines | unxed/ap 3c461fc, vendored in unxed/AI ac18f43 (+ gate resolves tee targets) |

## Open / next
- All queued retries are done. Minor: `tools/claims.py keys` crashes (traceback); `aistudio code` prints the whole
  edited block to stdout (noise); account-216 Progress line left as is.
- Next step for the owner: return to the regular loop (one round, 15 min pause) with one or two workers.

## How to continue (another agent)
- Skills installed from `~/dev/AI` (`~/.local/bin/aistudio`, `~/.claude/skills/*-offload`, `~/.claude/agents`).
- Spawn one `lunobot-haiku` subagent per task with: bot name/signature, work dir under `/tmp/lunobot-1/work/`,
  debug log path, exact steps. Read its debug log; on any DIAG/failure fix the skill in unxed/AI and retry.
- Rule from the owner: when routing to Gemini fails, improve the skill until it works; never just report.
