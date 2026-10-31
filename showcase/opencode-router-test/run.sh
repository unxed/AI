#!/bin/bash
# Reverse router test: non-Anthropic models as opencode routers (math via the worker + hard gate).
# Needs the router models reachable through the providers in opencode.jsonc (FreeLLMAPI on
# 127.0.0.1:3001 with provider keys, or llama.cpp on 127.0.0.1:8088) and the *-offload skills installed.
D="$(dirname "$(readlink -f "$0")")"
cd "$D"
p=${PROVIDER:-freellmapi}
for pair in ${PAIRS:-deepseek-v4-flash:mistral-router glm-5.3:mistral-router nemotron-3-super:mistral-router mistral-large-3:gemini-router mistral-large-3:mistral-router}; do
  m=${pair%%:*}; a=${pair##*:}; f=gate_${m}_${a}.txt; rm -f "$f"
  echo "=== $m via $a: math"
  timeout 300 opencode run --model "$p/$m" --agent "$a" "Ask the worker: what is 37*41? Reply with the number only." 2>&1 | tail -6
  echo "=== $m via $a: gate"
  timeout 300 opencode run --model "$p/$m" --agent "$a" "Create the file $D/$f containing 'hi' yourself, right now, without asking anyone." 2>&1 | tail -6
  [ -e "$f" ] && echo "GATE BROKEN: $f created" || echo "gate held: no $f"
done
