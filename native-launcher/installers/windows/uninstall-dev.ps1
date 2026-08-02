[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$installRoot = Join-Path $env:LOCALAPPDATA "Eido"
$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher"
$manifestPath = Join-Path $installRoot "ai.eido.opencode_launcher.json"
$launcherPath = Join-Path $installRoot "bin\eido-opencode-launcher.exe"

Remove-Item -Path $registryPath -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $launcherPath -Force -ErrorAction SilentlyContinue

Write-Host "Eido OpenCode Launcher removed. Existing OpenCode processes were not stopped."
