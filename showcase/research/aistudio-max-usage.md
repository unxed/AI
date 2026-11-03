# AI Studio: how to get closer to a human's usage (research, 2026-11-03)

Mechanism: a Claude Haiku router passed the question to Gemini through the `aistudio-offload`
skill (built-in browser). The answer came from gemini-3.1-pro-preview with Google Search
grounding on. The answer is unverified, and the model dated its knowledge July 2024, so the
quota numbers below are for Gemini 1.5 and are outdated.

## Points worth acting on (consistent with our own observations)
- Lower the concurrency on one account to 1-2 requests and queue the rest instead of running them in parallel.
- Reuse one tab: start a new chat inside it instead of opening a new tab for every request.
- Don't use the account from two IPs at once (laptop in the EU and VM in the US at the same time).
- Budget large prompts by tokens (~4 characters per token) and send very large ones to Flash rather than Pro.
- After "Permission denied" or a rate limit, back off exponentially: 60 s, then 120 s, and so on.
- Quotas are per account/project and per model. The UI shows no remaining-quota counter.

## Claims that need checking before relying on them
- The model claims that automating the web UI breaks Google's ToS when an API exists. The clause it
  quotes ("access ... other than through the interface we provide") does not obviously say that.
  It is the owner's call; read the current Google ToS and the AI Studio terms.
- "gemini.google.com has stricter anti-bot checks", "a model vanishing = its daily quota for you
  is spent", "Gemini CLI needs an API key": not verified, and the last one may be outdated
  (a personal Google sign-in used to be supported).
