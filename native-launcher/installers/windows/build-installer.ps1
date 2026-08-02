[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string[]] $ExtensionId,

    [ValidatePattern('^[0-9]+(\.[0-9]+){0,3}$')]
    [string] $Version = "0.1.4",

    [ValidateSet("amd64", "arm64")]
    [string] $Architecture = "amd64",

    [string] $OutputDirectory,
    [string] $GoBinary = "go",
    [string] $InnoCompiler = "",
    [switch] $Unsigned
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

function Find-InnoCompiler([string] $Requested) {
    if ($Requested) {
        return (Resolve-Path $Requested).Path
    }
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "Inno Setup 6 compiler (ISCC.exe) was not found."
}

function Find-SignTool {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $candidate = Get-ChildItem -LiteralPath $kitsRoot -Filter "signtool.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "signtool.exe was not found."
    }
    return $candidate.FullName
}

function Invoke-CodeSign([string] $Path) {
    $certificate = $env:EIDO_WINDOWS_SIGN_CERTIFICATE
    $password = $env:EIDO_WINDOWS_SIGN_PASSWORD
    if (-not $certificate -or -not $password) {
        throw "EIDO_WINDOWS_SIGN_CERTIFICATE and EIDO_WINDOWS_SIGN_PASSWORD are required for signed builds."
    }
    $timestampUrl = $env:EIDO_WINDOWS_TIMESTAMP_URL
    if (-not $timestampUrl) {
        $timestampUrl = "http://timestamp.digicert.com"
    }
    $signTool = Find-SignTool
    & $signTool sign /fd SHA256 /td SHA256 /tr $timestampUrl /f $certificate /p $password $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to sign $Path"
    }
    & $signTool verify /pa /v $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Signature verification failed for $Path"
    }
}

Assert-ExtensionIds $ExtensionId
$extensionIds = @($ExtensionId | Sort-Object -Unique)
$projectDirectory = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $projectDirectory "dist"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$innoCompilerPath = Find-InnoCompiler $InnoCompiler

$architectureLabel = if ($Architecture -eq "amd64") { "x64" } else { "arm64" }
$outputBaseName = "Eido-OpenCode-Launcher-$Version-Windows-$architectureLabel"
$workDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("eido-launcher-windows-" + [Guid]::NewGuid().ToString("N"))
$sourceRoot = Join-Path $workDirectory "payload"
$binaryDirectory = Join-Path $sourceRoot "bin"
New-Item -ItemType Directory -Force -Path $binaryDirectory | Out-Null

try {
    $launcherPath = Join-Path $binaryDirectory "eido-opencode-launcher.exe"
    $previousGoOs = $env:GOOS
    $previousGoArch = $env:GOARCH
    $previousCgoEnabled = $env:CGO_ENABLED
    try {
        $env:GOOS = "windows"
        $env:GOARCH = $Architecture
        $env:CGO_ENABLED = "0"
        Push-Location $projectDirectory
        try {
            $installerIds = $extensionIds -join ','
            $linkerFlags = "-s -w -H windowsgui -X github.com/eido-ai/eido-opencode-launcher/internal/launcher.LauncherVersion=$Version -X github.com/eido-ai/eido-opencode-launcher/internal/launcher.InstallerExtensionIDs=$installerIds"
            & $GoBinary build -trimpath -ldflags=$linkerFlags -o $launcherPath .\cmd\eido-opencode-launcher
            if ($LASTEXITCODE -ne 0) {
                throw "Go failed to build the Windows launcher."
            }
        } finally {
            Pop-Location
        }
    } finally {
        $env:GOOS = $previousGoOs
        $env:GOARCH = $previousGoArch
        $env:CGO_ENABLED = $previousCgoEnabled
    }

    if (-not $Unsigned) {
        Invoke-CodeSign $launcherPath
    }

    $manifestPath = Join-Path $sourceRoot "ai.eido.opencode_launcher.json"
    $manifest = [ordered]@{
        name = "ai.eido.opencode_launcher"
        description = "Launch OpenCode for authorized Chrome extensions"
        path = "__EIDO_LAUNCHER_PATH__"
        type = "stdio"
        allowed_origins = @($extensionIds | ForEach-Object { "chrome-extension://$_/" })
    } | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($manifestPath, $manifest, [System.Text.UTF8Encoding]::new($false))

    $env:EIDO_INSTALLER_VERSION = $Version
    $env:EIDO_INSTALLER_SOURCE = $sourceRoot
    $env:EIDO_INSTALLER_OUTPUT = $OutputDirectory
    $env:EIDO_INSTALLER_OUTPUT_BASENAME = $outputBaseName
    & $innoCompilerPath (Join-Path $PSScriptRoot "installer.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed to build the installer."
    }

    $installerPath = Join-Path $OutputDirectory "$outputBaseName.exe"
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        throw "Expected installer was not produced: $installerPath"
    }
    if (-not $Unsigned) {
        Invoke-CodeSign $installerPath
    }

    $hash = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $hashPath = "$installerPath.sha256"
    $hashLine = "$hash *$([System.IO.Path]::GetFileName($installerPath))`n"
    [System.IO.File]::WriteAllText($hashPath, $hashLine, [System.Text.UTF8Encoding]::new($false))

    Write-Host "Installer: $installerPath"
    Write-Host "Checksum: $hashPath"
} finally {
    Remove-Item -LiteralPath $workDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
