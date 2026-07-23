#!/bin/zsh
set -euo pipefail

usage() {
  cat <<'EOF'
Build the Eido OpenCode Launcher macOS installer.

Usage:
  build-package.sh --extension-id ID [options]

Options:
  --version VERSION          Numeric package version (default: 0.1.2)
  --output-dir DIRECTORY     Output directory (default: native-launcher/dist)
  --unsigned                Build an unsigned local verification package
  --skip-notarization       Sign the package but do not submit it to Apple
  --help                    Show this message

Signed builds require:
  EIDO_CODESIGN_IDENTITY             Developer ID Application identity
  EIDO_INSTALLER_IDENTITY            Developer ID Installer identity
  EIDO_NOTARY_KEYCHAIN_PROFILE       notarytool keychain profile
  EIDO_NOTARY_KEYCHAIN               Optional path to a non-default keychain

GO_BINARY may point to a specific Go executable.
EOF
}

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h:h}"
VERSION="0.1.2"
OUTPUT_DIR="$PROJECT_DIR/dist"
EXTENSION_ID=""
SIGNED_BUILD=true
NOTARIZE=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --extension-id)
      [[ $# -ge 2 ]] || { print -u2 "missing value for --extension-id"; exit 2; }
      EXTENSION_ID="$2"
      shift 2
      ;;
    --version)
      [[ $# -ge 2 ]] || { print -u2 "missing value for --version"; exit 2; }
      VERSION="$2"
      shift 2
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { print -u2 "missing value for --output-dir"; exit 2; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --unsigned)
      SIGNED_BUILD=false
      NOTARIZE=false
      shift
      ;;
    --skip-notarization)
      NOTARIZE=false
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      print -u2 "unknown option: $1"
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$EXTENSION_ID" =~ '^[a-p]{32}$' ]]; then
  print -u2 "--extension-id must be the fixed 32-character Chrome extension ID"
  exit 2
fi
if [[ ! "$VERSION" =~ '^[0-9]+([.][0-9]+){0,3}$' ]]; then
  print -u2 "--version must contain one to four numeric components"
  exit 2
fi

GO_BINARY="${GO_BINARY:-$(command -v go || true)}"
if [[ -z "$GO_BINARY" || ! -x "$GO_BINARY" ]]; then
  print -u2 "Go 1.22 or newer is required (or set GO_BINARY)"
  exit 2
fi

for tool in codesign lipo pkgbuild productbuild pkgutil shasum; do
  command -v "$tool" >/dev/null || { print -u2 "required tool not found: $tool"; exit 2; }
done
if $SIGNED_BUILD; then
  : "${EIDO_CODESIGN_IDENTITY:?EIDO_CODESIGN_IDENTITY is required for a signed build}"
  : "${EIDO_INSTALLER_IDENTITY:?EIDO_INSTALLER_IDENTITY is required for a signed build}"
fi
if $NOTARIZE; then
  : "${EIDO_NOTARY_KEYCHAIN_PROFILE:?EIDO_NOTARY_KEYCHAIN_PROFILE is required for notarization}"
  command -v xcrun >/dev/null || { print -u2 "xcrun is required for notarization"; exit 2; }
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/eido-launcher-pkg.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

BIN_DIR="$WORK_DIR/bin"
PAYLOAD_DIR="$WORK_DIR/payload"
PACKAGE_DIR="$WORK_DIR/packages"
mkdir -p "$BIN_DIR" "$PAYLOAD_DIR" "$PACKAGE_DIR" "$OUTPUT_DIR"

LDFLAGS="-s -w -X github.com/eido-ai/eido-opencode-launcher/internal/launcher.LauncherVersion=$VERSION"
for arch in amd64 arm64; do
  print "Building launcher for darwin/$arch..."
  (
    cd "$PROJECT_DIR"
    CGO_ENABLED=0 GOOS=darwin GOARCH="$arch" "$GO_BINARY" build \
      -trimpath \
      -ldflags="$LDFLAGS" \
      -o "$BIN_DIR/eido-opencode-launcher-$arch" \
      ./cmd/eido-opencode-launcher
  )
done

UNIVERSAL_BINARY="$BIN_DIR/eido-opencode-launcher"
lipo -create \
  "$BIN_DIR/eido-opencode-launcher-amd64" \
  "$BIN_DIR/eido-opencode-launcher-arm64" \
  -output "$UNIVERSAL_BINARY"
chmod 0755 "$UNIVERSAL_BINARY"

if $SIGNED_BUILD; then
  print "Signing launcher binary..."
  codesign --force --options runtime --timestamp \
    --identifier ai.eido.opencode-launcher \
    --sign "$EIDO_CODESIGN_IDENTITY" \
    "$UNIVERSAL_BINARY"
  codesign --verify --strict --verbose=2 "$UNIVERSAL_BINARY"
else
  print "Building unsigned verification package. Do not distribute this artifact."
fi

INSTALL_BIN_DIR="$PAYLOAD_DIR/Library/Application Support/Eido/bin"
HOST_DIR="$PAYLOAD_DIR/Library/Google/Chrome/NativeMessagingHosts"
mkdir -p "$INSTALL_BIN_DIR" "$HOST_DIR"
install -m 0755 "$UNIVERSAL_BINARY" "$INSTALL_BIN_DIR/eido-opencode-launcher"

cat > "$HOST_DIR/ai.eido.opencode_launcher.json" <<EOF
{
  "name": "ai.eido.opencode_launcher",
  "description": "Launch OpenCode for the Eido extension",
  "path": "/Library/Application Support/Eido/bin/eido-opencode-launcher",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF
chmod 0644 "$HOST_DIR/ai.eido.opencode_launcher.json"

COMPONENT_NAME="EidoOpenCodeLauncherComponent.pkg"
COMPONENT_PACKAGE="$PACKAGE_DIR/$COMPONENT_NAME"
pkgbuild \
  --root "$PAYLOAD_DIR" \
  --scripts "$SCRIPT_DIR/scripts" \
  --identifier ai.eido.opencode-launcher \
  --version "$VERSION" \
  --install-location / \
  --ownership recommended \
  "$COMPONENT_PACKAGE"

sed \
  -e "s/__VERSION__/$VERSION/g" \
  -e "s/__COMPONENT_PACKAGE__/$COMPONENT_NAME/g" \
  "$SCRIPT_DIR/distribution.xml.in" > "$WORK_DIR/distribution.xml"

FINAL_PACKAGE="$OUTPUT_DIR/Eido-OpenCode-Launcher-$VERSION.pkg"
rm -f "$FINAL_PACKAGE" "$FINAL_PACKAGE.sha256"
PRODUCT_ARGS=(
  --distribution "$WORK_DIR/distribution.xml"
  --resources "$SCRIPT_DIR/resources"
  --package-path "$PACKAGE_DIR"
)
if $SIGNED_BUILD; then
  PRODUCT_ARGS+=(--sign "$EIDO_INSTALLER_IDENTITY" --timestamp)
fi
productbuild "${PRODUCT_ARGS[@]}" "$FINAL_PACKAGE"

VERIFY_ARGS=()
if $SIGNED_BUILD; then
  VERIFY_ARGS+=(--require-signed)
fi
"$SCRIPT_DIR/verify-package.sh" "$FINAL_PACKAGE" "$EXTENSION_ID" "${VERIFY_ARGS[@]}"

if $NOTARIZE; then
  print "Submitting package to Apple Notary service..."
  NOTARY_ARGS=(--keychain-profile "$EIDO_NOTARY_KEYCHAIN_PROFILE")
  if [[ -n "${EIDO_NOTARY_KEYCHAIN:-}" ]]; then
    NOTARY_ARGS+=(--keychain "$EIDO_NOTARY_KEYCHAIN")
  fi
  xcrun notarytool submit "$FINAL_PACKAGE" "${NOTARY_ARGS[@]}" --wait --timeout 30m
  xcrun stapler staple "$FINAL_PACKAGE"
  xcrun stapler validate "$FINAL_PACKAGE"
  spctl --assess --verbose=2 --type install "$FINAL_PACKAGE"
fi

(
  cd "$OUTPUT_DIR"
  shasum -a 256 "${FINAL_PACKAGE:t}" > "${FINAL_PACKAGE:t}.sha256"
)

print "Installer: $FINAL_PACKAGE"
print "Checksum: $FINAL_PACKAGE.sha256"
