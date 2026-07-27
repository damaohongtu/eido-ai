#!/bin/zsh
set -euo pipefail

if [[ $# -lt 2 ]]; then
  print -u2 "usage: $0 PACKAGE (--extension-id ID ... | EXTENSION_ID) [--require-signed]"
  exit 2
fi

PACKAGE="$1"
shift
EXTENSION_IDS=()
REQUIRE_SIGNED=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --extension-id)
      [[ $# -ge 2 ]] || { print -u2 "missing value for --extension-id"; exit 2; }
      EXTENSION_IDS+=("$2")
      shift 2
      ;;
    --require-signed)
      REQUIRE_SIGNED="--require-signed"
      shift
      ;;
    *)
      # Backward-compatible single positional extension ID.
      if [[ "$1" =~ '^[a-p]{32}$' ]]; then
        EXTENSION_IDS+=("$1")
        shift
      else
        print -u2 "unknown option: $1"
        exit 2
      fi
      ;;
  esac
done

[[ -f "$PACKAGE" ]] || { print -u2 "package not found: $PACKAGE"; exit 2; }
[[ ${#EXTENSION_IDS[@]} -gt 0 ]] || { print -u2 "at least one Chrome extension ID is required"; exit 2; }
for extension_id in "${EXTENSION_IDS[@]}"; do
  [[ "$extension_id" =~ '^[a-p]{32}$' ]] || { print -u2 "invalid Chrome extension ID"; exit 2; }
done
EXTENSION_IDS=("${(@u)EXTENSION_IDS}")

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/eido-launcher-verify.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

pkgutil --expand-full "$PACKAGE" "$WORK_DIR/expanded"

PAYLOAD_ROOT="$(find "$WORK_DIR/expanded" -type d -name Payload -print -quit)"
[[ -n "$PAYLOAD_ROOT" ]] || { print -u2 "component package payload missing"; exit 1; }
BINARY="$PAYLOAD_ROOT/Library/Application Support/Eido/bin/eido-opencode-launcher"
MANIFEST="$PAYLOAD_ROOT/Library/Google/Chrome/NativeMessagingHosts/ai.eido.opencode_launcher.json"
[[ -x "$BINARY" ]] || { print -u2 "launcher binary missing or not executable"; exit 1; }
[[ -f "$MANIFEST" ]] || { print -u2 "Native Messaging manifest missing"; exit 1; }

grep -Fq '"name": "ai.eido.opencode_launcher"' "$MANIFEST" || {
  print -u2 "unexpected Native Messaging host name"
  exit 1
}
grep -Fq '"path": "/Library/Application Support/Eido/bin/eido-opencode-launcher"' "$MANIFEST" || {
  print -u2 "unexpected launcher path in manifest"
  exit 1
}
for extension_id in "${EXTENSION_IDS[@]}"; do
  grep -Fq "\"chrome-extension://$extension_id/\"" "$MANIFEST" || {
    print -u2 "package is missing extension ID: $extension_id"
    exit 1
  }
done
[[ "$(grep -c 'chrome-extension://' "$MANIFEST")" == "${#EXTENSION_IDS[@]}" ]] || {
  print -u2 "manifest allowed origins differ from the expected extension ID set"
  exit 1
}

ARCHITECTURES="$(lipo -archs "$BINARY")"
[[ "$ARCHITECTURES" == *"x86_64"* && "$ARCHITECTURES" == *"arm64"* ]] || {
  print -u2 "launcher is not a universal x86_64/arm64 binary"
  exit 1
}

if [[ "$REQUIRE_SIGNED" == "--require-signed" ]]; then
  codesign --verify --strict --verbose=2 "$BINARY"
  pkgutil --check-signature "$PACKAGE"
fi

print "Package verification passed: ${PACKAGE:t}"
