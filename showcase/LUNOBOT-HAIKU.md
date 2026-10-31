# Lunobot + offload: status and handoff (2026-10-31, ~23:10 UTC)

> ⛔ HARD OFFLOAD RULE (owner, no exceptions): the router never starts, studies or reasons about the task; managers/orchestrators are forbidden. Only exception: when offloading itself fails, the router may diagnose and fix the offload SKILL (unxed/AI), never the task.

## Current design (owner's spec)
- Router (cheap model) runs exactly one command: `aistudio drive --task-file ... -f LUNOBOT.md ...`. Gemini (AI Studio web UI) runs the whole Lunobot round; the engine executes Gemini's shell actions with safety rules. Router gate: `aistudio guard` (only one `aistudio ...` command).
- Runner: unxed/lunobot `runners/lunobot-round-opencode-gemini.sh` (router `opencode/glm-5.3-flash-free`, bot 2, drive model `gemini-3.8-flash` via LUNOBOT_DRIVE_MODEL; this account has no Pro access). Installed on g.2g0.ru (claude-box) in ~; skill there: ~/AI-repo (git pull to update). The OWNER starts rounds himself — agents must not.
- Commits: unxed/AI 0bf96e3 (drive mode, managers removed), d0667f0/d561b5a (hard rule everywhere); unxed/lunobot 96e823558 (runner on drive), cd99212 (flash default), 36b94f3/d310e72 (hard rule). ~/.claude/CLAUDE.md has the rule globally.

## In progress (may be on branch `wip/drive-diag-selffix` if unfinished)
- drive duplicates stderr to `<log>/stderr.log` + `result.json`; runner tails it live, logs status every 60 s, prints DIAG on failure.
- Rule exception text (skill self-fix on offload failure) next to the hard rule everywhere.
- Runner SKILL-FIX phase on drive failure: second opencode run limited to a fresh unxed/AI clone + diag dirs; fix, test, push, pull into ~/AI-repo.

## Known
- First drive round (started by owner 21:56 UTC, old runner version) used Pro -> Permission denied/rate limit fallbacks, slow; progress invisible in the runner terminal (fixed by the work above).
- Another session (Runcity) is adding rate-limit cooldown + model access cache to the engine.

## History (earlier today)
Haiku "manager" experiments were against the owner's rule and are removed (agents, guard --manager, runners). Results that landed: f4 triage dcc61b7, vtui#256 comment, D-05 status 092f7ce, goWidgets 24da9a4, account-216 state 938dacf. Engine fixes: 07f3e44, 1cc4c72, a410799, c6c476b, 0969655, 4b1fd23, ap 3c461fc / ac18f43.
