$ErrorActionPreference = "Stop"

$extensionId = "oggjajedgdgedecijokcknbbmfnpfjnc"
$updateUrl = "http://192.168.127.32:60088/extensions/eido/update.xml"
$crxUrl = "http://192.168.127.32:60088/extensions/eido/releases/0.1.7/eido-extension.crx"
$valueName = "1001"

$policyTargets = @(
    @{
        Browser = "Chrome"
        Path = "HKLM:\SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist"
    },
    @{
        Browser = "Edge"
        Path = "HKLM:\SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist"
    }
)

foreach ($target in $policyTargets) {
    if (-not (Test-Path $target.Path)) {
        throw "$($target.Browser) policy key is missing: $($target.Path)"
    }

    $actual = (Get-ItemProperty -Path $target.Path -Name $valueName).$valueName
    $expected = "$extensionId;$updateUrl"
    if ($actual -ne $expected) {
        throw "$($target.Browser) policy mismatch. Expected '$expected', got '$actual'."
    }

    Write-Host "$($target.Browser) registry policy: OK" -ForegroundColor Green
}

$updateResponse = Invoke-WebRequest -Uri $updateUrl -UseBasicParsing
if ($updateResponse.StatusCode -ne 200) {
    throw "Update manifest returned HTTP $($updateResponse.StatusCode)."
}
if ($updateResponse.Content -notmatch $extensionId) {
    throw "Update manifest does not contain the expected extension ID."
}
Write-Host "Update manifest: OK" -ForegroundColor Green

$headResponse = Invoke-WebRequest -Uri $crxUrl -Method Head -UseBasicParsing
if ($headResponse.StatusCode -ne 200) {
    throw "CRX returned HTTP $($headResponse.StatusCode)."
}
Write-Host "CRX download: OK" -ForegroundColor Green

Write-Host "Open chrome://policy and edge://policy, reload policies, then restart both browsers." -ForegroundColor Cyan
