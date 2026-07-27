#!/bin/zsh
set -euo pipefail

if [[ $# -lt 1 ]]; then
  print -u2 "usage: $0 EXTENSION_ID [EXTENSION_ID ...] [--go-binary PATH]"
  exit 2
fi

EXTENSION_IDS=()
GO_BINARY="${GO_BINARY:-$(command -v go || true)}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --go-binary)
      [[ $# -ge 2 ]] || { print -u2 "missing value for --go-binary"; exit 2; }
      GO_BINARY="$2"
      shift 2
      ;;
    *)
      # Backward compatibility: the former second positional argument could be a Go binary path.
      if [[ "$1" =~ '^[a-p]{32}$' ]]; then
        EXTENSION_IDS+=("$1")
        shift
      elif [[ ${#EXTENSION_IDS[@]} -eq 1 && -x "$1" ]]; then
        GO_BINARY="$1"
        shift
      else
        print -u2 "invalid Chrome extension ID or option: $1"
        exit 2
      fi
      ;;
  esac
done
if [[ ${#EXTENSION_IDS[@]} -eq 0 ]]; then
  print -u2 "at least one Chrome extension ID is required"
  exit 2
fi
EXTENSION_IDS=("${(@u)EXTENSION_IDS}")
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

ALLOWED_ORIGINS=""
for extension_id in "${EXTENSION_IDS[@]}"; do
  [[ -n "$ALLOWED_ORIGINS" ]] && ALLOWED_ORIGINS+=","$'\n'
  ALLOWED_ORIGINS+="    \"chrome-extension://$extension_id/\""
done

cat > "$HOST_MANIFEST" <<JSON
{
  "name": "ai.eido.opencode_launcher",
  "description": "Launch OpenCode for authorized Chrome extensions",
  "path": "$INSTALL_BIN",
  "type": "stdio",
  "allowed_origins": [
$ALLOWED_ORIGINS
  ]
}
JSON
chmod 0600 "$HOST_MANIFEST"

print "Eido OpenCode Launcher installed for ${#EXTENSION_IDS[@]} authorized extension(s): ${EXTENSION_IDS[*]}"
print "Reload the extension from chrome://extensions before testing."
