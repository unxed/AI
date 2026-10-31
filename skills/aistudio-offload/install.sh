#!/usr/bin/env bash
# Install aistudio-offload: a tiny Python venv (websockets) + Google Chrome.
# No Playwright/Selenium on purpose: Google detects them (sign-in is rejected and
# the account could be rate-limited). We drive a real Chrome over raw CDP instead.
# Works on small cloud VMs (tested on GCP e2-micro, 1 GB RAM, Ubuntu 24.04).
#   ./install.sh   -> venv in ~/.aistudio/venv, wrapper in ~/.local/bin/aistudio
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${AISTUDIO_HOME:-$HOME/.aistudio}/venv"

if ! python3 -c 'import ensurepip' 2>/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv
fi
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip websockets

if [ -z "${AISTUDIO_CHROME:-}" ] && ! command -v google-chrome >/dev/null && ! command -v chromium >/dev/null; then
  if sudo -n true 2>/dev/null && command -v apt-get >/dev/null; then
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/chrome.deb" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo apt-get install -y -qq "$tmp/chrome.deb"
    rm -rf "$tmp"
  else
    echo "Please install Google Chrome (or set AISTUDIO_CHROME=/path/to/chrome)." >&2
    exit 1
  fi
fi

# A virtual display lets Chrome run headed (no headless fingerprints) without any window.
if ! command -v xvfb-run >/dev/null && sudo -n true 2>/dev/null && command -v apt-get >/dev/null; then
  sudo apt-get install -y -qq xvfb >/dev/null || echo "xvfb not installed; falling back to --headless=new"
fi

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/aistudio" <<EOF
#!/bin/sh
exec "$VENV/bin/python" "$HERE/aistudio.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/aistudio"

# `ap` patcher (https://github.com/unxed/ap, vendored): the only patch format used for model-written code.
cat > "$HOME/.local/bin/ap" <<EOF
#!/bin/sh
exec python3 "$HERE/vendor/ap.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/ap"

# Small VMs: Chrome + AI Studio peak around 400-700 MB, make sure there is swap.
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
swap_kb=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 2000000 ] && [ "$swap_kb" -lt 1000000 ]; then
  echo "WARNING: <2 GB RAM and no swap. Recommended:"
  echo "  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
fi
echo "Installed. Next: aistudio login   (then: aistudio ask 'hello')"

# Claude Code subagents (router + manager). Claude Code loads agent types only at session start:
# restart the session after installing, or `subagent_type` is not found and no gate is attached.
if [ -d "$HOME/.claude" ]; then
  mkdir -p "$HOME/.claude/agents"
  cp "$HERE"/agents/claude/*.md "$HOME/.claude/agents/"
  echo "Installed Claude Code agents: $(ls "$HERE"/agents/claude | tr '\n' ' ')(restart Claude Code to load them)"
fi
