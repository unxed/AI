# Offload experiment: status and handoff (2026-10-31)

Goal: a cheap router model (Claude Haiku, or a free/open model) never works on a task itself; it
only drives a vendor's **web chat UI** in a real Chrome (never the API) via the skills in
`../skills` (aistudio / mistral / deepseek / grok). Rules: router hard gate, no offload to the
same vendor anywhere in a chain, model code only as `ap` patches, **no builds/tests on the
e2-micro VM** (use `code --ci`, i.e. GitHub Actions).

## Done and verified
- Claude Haiku as router works (it is also the cheapest Anthropic model, so that is the answer).
- Showcase PRs, written by Gemini through `aistudio code`, routed by Haiku, merged with green CI:
  - unxed/lunobot#285 (issue #262: don't merge a train while main CI runs) - tasks/lunobot262*.md
  - unxed/zipper#43 (issue #42: remove entries from TAR archives, + coverage tests) - tasks/zipper42*.md
- ap: the `found` UnboundLocalError and the indentation-only REPLACE no-op are fixed in unxed/ap main.
  The vendored copies in `skills/*/vendor/ap` are synced.
- AI Studio on the GCP e2-micro VM (unxed@35.209.76.8, Xvfb + real Chrome): 3/3 current models
  answer (21-75 s each), no "Permission denied". gemini-2.5-flash is no longer offered in the chat UI.
- Mistral Le Chat: e2e on the laptop and the VM; Luna (opencode) -> mistral-router works, and the gate holds.
- DeepSeek web: Google SSO login in the shared profile `~/.offload-browser` (laptop); `deepseek-chat ask` e2e OK.
- Vendor-chain refusal works (`OFFLOAD_CALLER=deepseek-... deepseek-chat ask` -> refused).

## Open
1. Reverse router tests (DeepSeek / GLM / Nemotron / Mistral as opencode routers): `opencode-router-test/`.
   - Blocked: opencode's free tier is exhausted.
   - FreeLLMAPI (laptop, docker, 127.0.0.1:3001; it autostarts because docker is enabled and the
     container has `restart: unless-stopped`) only has a Google key. The owner must add provider keys
     (Mistral, NVIDIA NIM, Zhipu/GLM, DeepSeek, OpenRouter) in its dashboard.
   - Owner decision (2026-10-31): no keys will be added, so this test is skipped via FreeLLMAPI.
     Rerun `./opencode-router-test/run.sh` only if keys or another free provider appear.
2. Local quantized model as router.
   - llama.cpp b12017 CPU is at `~/opt/llama/dl/llama-b12017/`.
   - The model is `~/opt/llama/models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (unsloth, HF).
   - Serve it: `llama-server -m <gguf> --jinja -c 16384 --port 8088`.
   - Test it: `PROVIDER=llamacpp PAIRS=qwen3-4b:mistral-router ./opencode-router-test/run.sh`.
3. Grok in X: the skill is installed on the laptop, but the X login fails.
   - "Continue with Google" opens the Google popup and the account gets picked, then X silently
     stays logged out.
   - Probably no X account is linked to that Google account. Do not create one; the owner logs in
     by hand with `grok login`.
4. FreeLLMAPI on the VM: undecided (1 GB RAM is shared with Chrome). The alternative is an SSH
   tunnel to the laptop's instance.
5. README for unxed/AI (overview + results above).
