#!/usr/bin/env bash
# Install aistudio-offload: a Python venv with Playwright + headless Chromium.
# Works on small cloud VMs (tested on GCP e2-micro, 1 GB RAM, Ubuntu 24.04).
#   ./install.sh            -> venv in ~/.aistudio/venv, wrapper in ~/.local/bin/aistudio
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${AISTUDIO_HOME:-$HOME/.aistudio}/venv"

if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' 2>/dev/null; then
  sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv
fi
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip playwright

# Headless shell is ~half the size/RAM of full Chromium; enough for AI Studio.
if [ -n "${AISTUDIO_CHROME:-}" ]; then
  echo "Using AISTUDIO_CHROME=$AISTUDIO_CHROME"
elif sudo -n true 2>/dev/null; then
  "$VENV/bin/playwright" install --with-deps --only-shell chromium
else
  "$VENV/bin/playwright" install --only-shell chromium
  echo "No sudo: if Chromium fails to start, ask an admin to run: $VENV/bin/playwright install-deps chromium"
fi

mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/aistudio" <<EOF
#!/bin/sh
exec "$VENV/bin/python" "$HERE/aistudio.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/aistudio"

# Small VMs: make sure there is some swap, Chromium + AI Studio peak around 600-800 MB.
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
swap_kb=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
if [ "$mem_kb" -lt 2000000 ] && [ "$swap_kb" -lt 1000000 ]; then
  echo "WARNING: <2 GB RAM and no swap. Recommended:"
  echo "  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile"
fi
echo "Installed. Next: aistudio login   (then: aistudio ask 'hello')"
