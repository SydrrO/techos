param(
    [string]$HostAlias = "techos-server",
    [string]$RemoteDir = "/opt/sydrro-techos"
)

$ErrorActionPreference = "Stop"

$DataFiles = @(
    "sydrro-data.sqlite3",
    "sydrro-backup.json",
    "data.xlsx"
)

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$existing = $DataFiles | Where-Object { Test-Path -LiteralPath $_ }
if ($existing.Count) {
    $backup = Join-Path (Get-Location) "local-data-backup-$timestamp.zip"
    Compress-Archive -Path $existing -DestinationPath $backup -Force
    Write-Host "Local backup: $backup"
}

$stage = Join-Path $env:TEMP "sydrro-server-data-$timestamp"
New-Item -ItemType Directory -Path $stage | Out-Null

$scpArgs = @()
foreach ($name in $DataFiles) {
    $scpArgs += "${HostAlias}:$RemoteDir/$name"
}
$scpArgs += "$stage\"
Invoke-Checked -FilePath "scp" -Arguments $scpArgs

$env:SYDRRO_STAGE = $stage
@'
import json
import os
import sqlite3

stage = os.environ["SYDRRO_STAGE"]
with open(os.path.join(stage, "sydrro-backup.json"), encoding="utf-8") as fh:
    json.load(fh)

conn = sqlite3.connect(os.path.join(stage, "sydrro-data.sqlite3"))
try:
    print("sqlite quick_check:", conn.execute("pragma quick_check").fetchone()[0])
finally:
    conn.close()
'@ | python -
if ($LASTEXITCODE -ne 0) {
    throw "Downloaded data validation failed"
}

foreach ($name in $DataFiles) {
    Copy-Item -LiteralPath (Join-Path $stage $name) -Destination (Join-Path (Get-Location) $name) -Force
}

Get-ChildItem $DataFiles | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
Write-Host "Server data pulled into local workspace."
