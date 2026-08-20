param(
    [string]$PreparedBuilder = (Join-Path $PSScriptRoot "..\..\_port_automation"),
    [string]$BuildTools = (Join-Path $PSScriptRoot "..\..\_analysis\tools"),
    [string]$BaselineZip = (Join-Path $PSScriptRoot "..\..\_build305\houji_HyperOS4_CN_OS4.0.0.9_on_OS3.0.305_v1_no-root.zip")
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$prepared = (Resolve-Path -LiteralPath $PreparedBuilder).Path
$toolSource = (Resolve-Path -LiteralPath $BuildTools).Path
$baseline = (Resolve-Path -LiteralPath $BaselineZip).Path

if (-not (Test-Path -LiteralPath $baseline -PathType Leaf)) {
    throw "Baseline port ZIP was not found: $baseline"
}

function Set-LocalJunction {
    param(
        [string]$Name,
        [string]$Target
    )

    if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
        throw "Folder was not found: $Target"
    }

    $destination = Join-Path $repo $Name
    if (Test-Path -LiteralPath $destination) {
        $item = Get-Item -LiteralPath $destination -Force
        if ($item.LinkType -eq "Junction") {
            Remove-Item -LiteralPath $destination
        }
        elseif ($item.PSIsContainer -and -not (Get-ChildItem -LiteralPath $destination -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $destination
        }
        else {
            throw "Refusing to replace a non-empty local folder: $destination"
        }
    }

    New-Item -ItemType Junction -Path $destination -Target $Target | Out-Null
    Write-Host "Linked $Name -> $Target"
}

Set-LocalJunction -Name "patches" -Target (Join-Path $prepared "patches")
Set-LocalJunction -Name "base_dynamic" -Target (Join-Path $prepared "base_dynamic")
Set-LocalJunction -Name "tools" -Target $toolSource

$localConfig = [ordered]@{
    baseline_port_zip = $baseline
}
$localConfig | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repo "config.local.json") -Encoding utf8
Write-Host "Saved config.local.json"

if (Test-Path -LiteralPath (Join-Path $repo ".git")) {
    git -C $repo config core.hooksPath .githooks
    Write-Host "Enabled the repository size guard"
}
