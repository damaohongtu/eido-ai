[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string[]] $ExtensionId,

    [string] $GoBinary = "go"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-ExtensionIds([string[]] $Ids) {
    if ($Ids.Count -eq 0) {
        throw "At least one Chrome extension ID is required."
    }
    foreach ($id in $Ids) {
        if ($id -notmatch '^[a-p]{32}$') {
            throw "Invalid Chrome extension ID: $id"
        }
    }
}

Assert-ExtensionIds $ExtensionId
$extensionIds = @($ExtensionId | Sort-Object -Unique)
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$installRoot = Join-Path $env:LOCALAPPDATA "Eido"
$binaryDirectory = Join-Path $installRoot "bin"
$launcherPath = Join-Path $binaryDirectory "eido-opencode-launcher.exe"
$manifestPath = Join-Path $installRoot "ai.eido.opencode_launcher.json"
$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher"

New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $installRoot "logs") | Out-Null

Push-Location $projectDirectory
try {
    $installerIds = $extensionIds -join ','
    $linkerFlags = "-s -w -H windowsgui -X github.com/eido-ai/eido-opencode-launcher/internal/launcher.InstallerExtensionIDs=$installerIds"
    & $GoBinary build -trimpath -ldflags=$linkerFlags -o $launcherPath .\cmd\eido-opencode-launcher
    if ($LASTEXITCODE -ne 0) {
        throw "Go failed to build the development launcher."
    }
} finally {
    Pop-Location
}

$manifest = [ordered]@{
    name = "ai.eido.opencode_launcher"
    description = "Launch OpenCode for authorized Chrome extensions"
    path = $launcherPath
    type = "stdio"
    allowed_origins = @($extensionIds | ForEach-Object { "chrome-extension://$_/" })
} | ConvertTo-Json -Depth 4
[System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

New-Item -Path $registryPath -Force | Out-Null
Set-Item -Path $registryPath -Value $manifestPath

Write-Host "Eido OpenCode Launcher installed for $($extensionIds.Count) authorized extension(s): $($extensionIds -join ', ')"
Write-Host "Completely exit and reopen Chrome before testing."
