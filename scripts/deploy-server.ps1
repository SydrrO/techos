param(
    [string]$HostAlias = "techos-server",
    [string]$RemoteDir = "/opt/sydrro-techos",
    [string]$ServiceName = "sydrro-techos",
    [switch]$AllowDataOverwrite,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$CodeFiles = @(
    "SYDRRO-TECH.html",
    "index.html",
    "sydrro-local-server.py",
    "README.md",
    "auth-config.json"
)

$DataFiles = @(
    "sydrro-data.sqlite3",
    "sydrro-backup.json",
    "data.xlsx"
)

$Files = @($CodeFiles)
if ($AllowDataOverwrite) {
    Write-Warning "AllowDataOverwrite is enabled. Server runtime data will be replaced by local files."
    $Files += $DataFiles
}

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

function Get-LocalHashMap {
    param([string[]]$Names)
    $map = @{}
    foreach ($name in $Names) {
        if (-not (Test-Path -LiteralPath $name)) {
            throw "Missing local file: $name"
        }
        $hash = (Get-FileHash -LiteralPath $name -Algorithm SHA256).Hash.ToLowerInvariant()
        $map[$name] = $hash
    }
    return $map
}

function Get-RemoteHashMap {
    param([string[]]$Names)
    $quoted = ($Names | ForEach-Object { "'$_'" }) -join " "
    $command = "cd '$RemoteDir' && sha256sum $quoted 2>/dev/null || true"
    $lines = & ssh $HostAlias $command
    if ($LASTEXITCODE -ne 0) {
        throw "ssh failed while reading remote hashes"
    }

    $map = @{}
    foreach ($line in $lines) {
        if ($line -match "^([0-9a-fA-F]{64})\s+\*?(.+)$") {
            $map[$Matches[2].Trim()] = $Matches[1].ToLowerInvariant()
        }
    }
    return $map
}

$localHashes = Get-LocalHashMap -Names $Files
$remoteHashes = Get-RemoteHashMap -Names $Files

$changed = @()
foreach ($name in $Files) {
    if (-not $remoteHashes.ContainsKey($name) -or $remoteHashes[$name] -ne $localHashes[$name]) {
        $changed += $name
    }
}

if (-not $changed.Count) {
    Write-Host "Server is already up to date. No files uploaded."
    exit 0
}

Write-Host "Files to deploy:"
$changed | ForEach-Object { Write-Host "  $_" }

if (-not $AllowDataOverwrite) {
    $blocked = $changed | Where-Object { $DataFiles -contains $_ }
    if ($blocked.Count) {
        throw "Internal guard failed: data files are in the deploy set without AllowDataOverwrite."
    }
}

if ($DryRun) {
    Write-Host "DryRun enabled. No changes made."
    exit 0
}

$remoteChanged = ($changed | ForEach-Object { "'$_'" }) -join " "
$backupCommand = "set -e; ts=`$(date +%Y%m%d%H%M%S); backup=/root/sydrro-techos-pre-deploy-`$ts.tgz; cd '$RemoteDir'; tar czf `"`$backup`" $remoteChanged; echo BACKUP=`$backup"
Invoke-Checked -FilePath "ssh" -Arguments @($HostAlias, $backupCommand)

$remoteStage = "/tmp/sydrro-deploy-upload"
Invoke-Checked -FilePath "ssh" -Arguments @($HostAlias, "rm -rf '$remoteStage' && mkdir -p '$remoteStage'")

$scpArgs = @()
foreach ($name in $changed) {
    $scpArgs += (Join-Path (Get-Location) $name)
}
$scpArgs += "${HostAlias}:$remoteStage/"
Invoke-Checked -FilePath "scp" -Arguments $scpArgs

$validateParts = @(
    "set -e",
    "cd '$remoteStage'"
)
if ($changed -contains "sydrro-local-server.py") {
    $validateParts += "python3 -m py_compile sydrro-local-server.py"
}
if ($changed -contains "auth-config.json") {
    $validateParts += "python3 -m json.tool auth-config.json >/dev/null"
}
if ($changed -contains "sydrro-backup.json") {
    $validateParts += "python3 -m json.tool sydrro-backup.json >/dev/null"
}
if ($changed -contains "sydrro-data.sqlite3") {
    $validateParts += "python3 -c `"import sqlite3; c=sqlite3.connect('sydrro-data.sqlite3'); print('sqlite quick_check:', c.execute('pragma quick_check').fetchone()[0]); c.close()`""
}
Invoke-Checked -FilePath "ssh" -Arguments @($HostAlias, ($validateParts -join "; "))

$installLines = @(
    "set -e",
    "systemctl stop '$ServiceName'"
)
foreach ($name in $changed) {
    $mode = if (($DataFiles -contains $name) -or $name -eq "auth-config.json") { "600" } else { "644" }
    $installLines += "install -m $mode '$remoteStage/$name' '$RemoteDir/$name'"
}
$installLines += "systemctl start '$ServiceName'"
$installLines += "sleep 2"
$installLines += "systemctl is-active '$ServiceName'"
$installLines += "rm -rf '$remoteStage'"
Invoke-Checked -FilePath "ssh" -Arguments @($HostAlias, ($installLines -join "; "))

Write-Host "Deployment complete. Data overwrite:" $AllowDataOverwrite.IsPresent
