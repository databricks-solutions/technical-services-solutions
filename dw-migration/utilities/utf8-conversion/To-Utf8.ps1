<#
.SYNOPSIS
  Bulk-convert UTF-16 files (with BOM) to UTF-8 (no BOM) for Lakebridge / Genie Migrate.
.DESCRIPTION
  - Writes converted copies to -Out, keeping the folder structure. Source files are never modified.
  - Converts only files that start with a UTF-16 BOM; every other file is copied unchanged.
  - XML exports (.dtsx, .xml, ...): rewrites the declaration encoding="utf-16" to "utf-8".
  - Skips hidden files/folders and the output folder itself (it may sit inside the source).
  Requires Windows PowerShell 5.1 or PowerShell 7.
.EXAMPLE
  .\To-Utf8.ps1 -Src C:\export -Out C:\export_utf8
#>
param([Parameter(Mandatory)][string]$Src, [Parameter(Mandatory)][string]$Out)
$srcRoot = (Resolve-Path $Src).Path.TrimEnd('\', '/')
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$converted = 0
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$outRoot = (Resolve-Path $Out).Path.TrimEnd('\', '/')
Get-ChildItem -Path $srcRoot -File -Recurse |
  Where-Object { -not $_.FullName.StartsWith($outRoot + [IO.Path]::DirectorySeparatorChar) } |
  Where-Object { $_.FullName.Substring($srcRoot.Length) -notmatch '[\\/]\.' } |
  ForEach-Object {
    $rel  = $_.FullName.Substring($srcRoot.Length).TrimStart('\', '/')
    $dest = Join-Path $Out $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    $b = [System.IO.File]::ReadAllBytes($_.FullName)
    $isUtf16 = $b.Length -ge 2 -and (($b[0] -eq 0xFF -and $b[1] -eq 0xFE) -or ($b[0] -eq 0xFE -and $b[1] -eq 0xFF))
    if ($isUtf16) {
        $text = [System.IO.File]::ReadAllText($_.FullName)   # BOM-aware decode
        # XML-based exports (.dtsx, .xml): fix the declared encoding too
        $text = $text -replace '^(<\?xml[^>]*encoding=")utf-16(")', '${1}utf-8${2}'
        [System.IO.File]::WriteAllText($dest, $text, $utf8NoBom)
        Write-Host "converted: $rel"; $converted++
    } else {
        Copy-Item -LiteralPath $_.FullName -Destination $dest
    }
}
Write-Host "Done. $converted file(s) converted to UTF-8 in $Out"
