param(
    [string]$BuildTools = (Join-Path $PSScriptRoot "..\..\_analysis\tools")
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not (Test-Path -LiteralPath $BuildTools -PathType Container)) {
    throw "Build tools were not found: $BuildTools. Pass the tools folder as the first argument."
}

$toolSource = (Resolve-Path -LiteralPath $BuildTools).Path
$destination = Join-Path $repo "tools"

if (Test-Path -LiteralPath $destination) {
    $item = Get-Item -LiteralPath $destination -Force
    if ($item.LinkType -eq "Junction") {
        Remove-Item -LiteralPath $destination
    }
    elseif ($item.PSIsContainer -and -not (Get-ChildItem -LiteralPath $destination -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $destination
    }
    else {
        throw "Refusing to replace a non-empty tools folder: $destination"
    }
}

New-Item -ItemType Junction -Path $destination -Target $toolSource | Out-Null
Write-Host "Linked tools -> $toolSource"

if (Test-Path -LiteralPath (Join-Path $repo ".git")) {
    git -C $repo config core.hooksPath .githooks
    Write-Host "Enabled the repository size guard"
}
