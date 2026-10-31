#!/usr/bin/env bash
# grok-offload reuses the aistudio-offload engine (venv + Google Chrome, no Playwright).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE="${AISTUDIO_DIR:-$HERE/../aistudio-offload}"
VENV="$HOME/.aistudio/venv"
[ -x "$VENV/bin/python" ] || "$ENGINE/install.sh"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/grok" <<EOW
#!/bin/sh
exec "$VENV/bin/python" "$HERE/grok.py" "\$@"
EOW
chmod +x "$HOME/.local/bin/grok"
echo "Installed. Next: grok login   (then: grok ask 'hello')"
