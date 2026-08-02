[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]] $ExtensionId,

    [string] $InstallRoot = (Join-Path $env:LOCALAPPDATA "Eido")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$extensionIds = @($ExtensionId | Sort-Object -Unique)
foreach ($id in $extensionIds) {
    if ($id -notmatch '^[a-p]{32}$') {
        throw "Invalid Chrome extension ID: $id"
    }
}

$launcherPath = Join-Path $InstallRoot "bin\eido-opencode-launcher.exe"
$manifestPath = Join-Path $InstallRoot "ai.eido.opencode_launcher.json"
$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher"

if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Launcher executable is missing: $launcherPath"
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Native Messaging manifest is missing: $manifestPath"
}
if (-not (Test-Path -Path $registryPath)) {
    throw "Chrome Native Messaging registry key is missing."
}

$registeredManifest = (Get-Item -Path $registryPath).GetValue("")
if (-not [string]::Equals($registeredManifest, $manifestPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Chrome registry entry points to an unexpected manifest: $registeredManifest"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.name -ne "ai.eido.opencode_launcher" -or $manifest.type -ne "stdio") {
    throw "Native Messaging manifest has unexpected metadata."
}
if (-not [string]::Equals($manifest.path, $launcherPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Native Messaging manifest points to an unexpected launcher: $($manifest.path)"
}
$expectedOrigins = @($extensionIds | ForEach-Object { "chrome-extension://$_/" } | Sort-Object)
$actualOrigins = @($manifest.allowed_origins | Sort-Object)
if (($expectedOrigins -join "`n") -ne ($actualOrigins -join "`n")) {
    throw "Native Messaging allowed_origins do not match the expected extension IDs."
}

Write-Host "Windows installation verification passed: $InstallRoot"
