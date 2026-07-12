#!/bin/zsh
set -euo pipefail

rm -f "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/ai.eido.opencode_launcher.json"
rm -f "$HOME/Library/Application Support/Eido/bin/eido-opencode-launcher"
print "Eido OpenCode Launcher removed. Existing OpenCode processes were not stopped."
