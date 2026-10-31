#!/usr/bin/env bash
# Install mistral-offload: a tiny Python venv (websockets) + Google Chrome. No Playwright
# (Google and others detect automation frameworks); a real Chrome is driven over raw CDP.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="${MISTRAL_HOME:-$HOME/.mistral-offload}/venv"

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
cat > "$HOME/.local/bin/mistral-chat" <<EOW
#!/bin/sh
exec "$VENV/bin/python" "$HERE/mistral_chat.py" "\$@"
EOW
chmod +x "$HOME/.local/bin/mistral-chat"

# `ap` patcher (https://github.com/unxed/ap, vendored): the only patch format used for model-written code.
cat > "$HOME/.local/bin/ap" <<EOF
#!/bin/sh
exec python3 "$HERE/vendor/ap.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/ap"
echo "Installed. Next: mistral-chat login   (then: mistral-chat ask 'hello')"
