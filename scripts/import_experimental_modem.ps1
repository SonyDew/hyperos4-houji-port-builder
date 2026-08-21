param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$local = Join-Path $repo "local"
$target = Join-Path $local "modemfirmware_ww.img"
$temporary = Join-Path $local "modemfirmware_ww.img.importing"
New-Item -ItemType Directory -Force -Path $local | Out-Null
Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue

$extension = [IO.Path]::GetExtension($sourcePath).ToLowerInvariant()
if ($extension -eq ".img") {
    Copy-Item -LiteralPath $sourcePath -Destination $temporary -Force
}
elseif ($extension -eq ".zip") {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($sourcePath)
    try {
        $entry = $archive.GetEntry("images/modemfirmware_ww.img")
        if ($null -eq $entry) {
            $entry = $archive.GetEntry("modemfirmware_ww.img")
        }
        if ($null -eq $entry) {
            throw "The ZIP does not contain modemfirmware_ww.img"
        }
        $inputStream = $entry.Open()
        $outputStream = [IO.File]::Create($temporary)
        try {
            $inputStream.CopyTo($outputStream)
        }
        finally {
            $outputStream.Dispose()
            $inputStream.Dispose()
        }
    }
    finally {
        $archive.Dispose()
    }
}
else {
    throw "Use an IMG file or a ZIP containing modemfirmware_ww.img"
}

$expectedSize = 223334400
$expectedHash = "EA44893F62DFD38F237F2B52539A65C9DB44EED8A4712B3F2148E17131D92404"
$item = Get-Item -LiteralPath $temporary
$hash = (Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash
if ($item.Length -ne $expectedSize -or $hash -ne $expectedHash) {
    Remove-Item -LiteralPath $temporary
    throw "The experimental modem is not the verified build. It was not imported."
}

Move-Item -LiteralPath $temporary -Destination $target -Force
Write-Host "Experimental modem is ready: $target"
