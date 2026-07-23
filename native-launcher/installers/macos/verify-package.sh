#!/bin/zsh
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  print -u2 "usage: $0 PACKAGE EXTENSION_ID [--require-signed]"
  exit 2
fi

PACKAGE="$1"
EXTENSION_ID="$2"
REQUIRE_SIGNED="${3:-}"

[[ -f "$PACKAGE" ]] || { print -u2 "package not found: $PACKAGE"; exit 2; }
[[ "$EXTENSION_ID" =~ '^[a-p]{32}$' ]] || { print -u2 "invalid Chrome extension ID"; exit 2; }
[[ -z "$REQUIRE_SIGNED" || "$REQUIRE_SIGNED" == "--require-signed" ]] || {
  print -u2 "unknown option: $REQUIRE_SIGNED"
  exit 2
}

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
grep -Fq "\"chrome-extension://$EXTENSION_ID/\"" "$MANIFEST" || {
  print -u2 "package was built for a different extension ID"
  exit 1
}
[[ "$(grep -c 'chrome-extension://' "$MANIFEST")" == "1" ]] || {
  print -u2 "manifest must contain exactly one allowed extension origin"
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
