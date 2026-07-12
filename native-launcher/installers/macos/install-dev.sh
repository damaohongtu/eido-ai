#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  print -u2 "usage: $0 EXTENSION_ID [GO_BINARY]"
  exit 2
fi

EXTENSION_ID="$1"
GO_BINARY="${2:-$(command -v go || true)}"
if [[ ! "$EXTENSION_ID" =~ '^[a-p]{32}$' ]]; then
  print -u2 "invalid Chrome extension ID"
  exit 2
fi
if [[ -z "$GO_BINARY" || ! -x "$GO_BINARY" ]]; then
  print -u2 "Go is required to build the development launcher"
  exit 2
fi

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h:h}"
INSTALL_ROOT="$HOME/Library/Application Support/Eido"
INSTALL_BIN="$INSTALL_ROOT/bin/eido-opencode-launcher"
HOST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
HOST_MANIFEST="$HOST_DIR/ai.eido.opencode_launcher.json"

mkdir -p "${INSTALL_BIN:h}" "$HOST_DIR" "$HOME/Library/Logs/Eido"
pushd "$PROJECT_DIR" >/dev/null
"$GO_BINARY" build -trimpath -ldflags="-s -w" -o "$INSTALL_BIN" ./cmd/eido-opencode-launcher
popd >/dev/null
chmod 0700 "$INSTALL_BIN"

cat > "$HOST_MANIFEST" <<JSON
{
  "name": "ai.eido.opencode_launcher",
  "description": "Launch OpenCode for the Eido extension",
  "path": "$INSTALL_BIN",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
JSON
chmod 0600 "$HOST_MANIFEST"

print "Eido OpenCode Launcher installed for extension $EXTENSION_ID"
print "Reload the extension from chrome://extensions before testing."
