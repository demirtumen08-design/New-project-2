$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
$LogPath = Join-Path $LogDir "growthos-watchdog.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, "Global\GrowthOSModelBWatchdog", [ref] $createdNew)
if (-not $createdNew) {
    exit 0
}

function Write-WatchdogLog {
    param([string] $Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$stamp] $Message" -Encoding UTF8
}

function Start-GrowthOsModelB {
    Write-WatchdogLog "Model B servisleri baslatiliyor."
    $command = "nohup bash -c 'exec -a growthos-keepalive sleep infinity' >/dev/null 2>&1 & systemctl start growth-os nginx named 2>/dev/null || true; systemctl is-active growth-os; systemctl is-active nginx"
    & wsl -d Ubuntu -u root -- bash -lc $command |
        ForEach-Object { Write-WatchdogLog $_ }
}

Write-WatchdogLog "Watchdog basladi."
Start-GrowthOsModelB

while ($true) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1/healthz" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -ne 200 -or $response.Content.Trim() -ne "ok") {
            Write-WatchdogLog "Health check beklenen cevabi vermedi."
            Start-GrowthOsModelB
        }
    } catch {
        Write-WatchdogLog "Health check basarisiz: $($_.Exception.Message)"
        Start-GrowthOsModelB
    }
    Start-Sleep -Seconds 60
}
