$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$runningApp = Get-Process -Name TurkiyeGundemiApp -ErrorAction SilentlyContinue
if ($runningApp) {
    $runningApp | Stop-Process -Force
    Start-Sleep -Seconds 1
}

python -m compileall src
python -m PyInstaller -y --clean --noconsole --name TurkiyeGundemiApp launch_desktop.py

$Package = Join-Path $Root "dist\TurkiyeGundemiApp"
$Workspace = Join-Path $Package "workspace"
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null

foreach ($dir in @("config", "content", "docs", "reports", "sites", "ops", "tools")) {
    $source = Join-Path $Root $dir
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination $Workspace -Recurse -Force
    }
}

Copy-Item -Path (Join-Path $Root "README.md") -Destination $Package -Force

$startupTask = Get-ScheduledTask -TaskName "GrowthOS-Start-ModelB" -ErrorAction SilentlyContinue
if ($startupTask) {
    Start-ScheduledTask -TaskName "GrowthOS-Start-ModelB"
    Start-Sleep -Seconds 3
}

Write-Output "Package ready: $Package\TurkiyeGundemiApp.exe"
