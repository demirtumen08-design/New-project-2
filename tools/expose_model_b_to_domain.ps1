param(
    [string]$Distro = "Ubuntu",
    [string]$LanIPv4 = "",
    [string]$PublicIPv4 = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Distro", "`"$Distro`""
    )
    if ($LanIPv4) { $args += @("-LanIPv4", "`"$LanIPv4`"") }
    if ($PublicIPv4) { $args += @("-PublicIPv4", "`"$PublicIPv4`"") }
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -Verb RunAs -Wait
    exit $LASTEXITCODE
}

if (-not $LanIPv4) {
    $LanIPv4 = (Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -like "192.168.*" -or $_.IPAddress -like "10.*" -or $_.IPAddress -like "172.*" } |
        Where-Object { $_.InterfaceAlias -notlike "*WSL*" -and $_.IPAddress -notlike "172.25.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
}

if (-not $PublicIPv4) {
    try {
        $PublicIPv4 = (Invoke-RestMethod -Uri "https://api.ipify.org?format=json" -TimeoutSec 10).ip
    } catch {
        $PublicIPv4 = ""
    }
}

$wslIp = (& wsl -d $Distro -- bash -lc "hostname -I | awk '{print `$1}'").Trim()
if (-not $wslIp) {
    throw "WSL IP bulunamadi. Once Ubuntu/Model B calismali."
}

$rules = @(
    @{ Name = "GrowthOS-HTTP-80"; Display = "Growth OS HTTP 80"; Protocol = "TCP"; Port = "80" },
    @{ Name = "GrowthOS-HTTPS-443"; Display = "Growth OS HTTPS 443"; Protocol = "TCP"; Port = "443" }
)

foreach ($rule in $rules) {
    if (-not (Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule `
            -Name $rule.Name `
            -DisplayName $rule.Display `
            -Direction Inbound `
            -Action Allow `
            -Protocol $rule.Protocol `
            -LocalPort $rule.Port `
            -Profile Any | Out-Null
    }
}

foreach ($port in 80, 443) {
    foreach ($address in "0.0.0.0", $LanIPv4) {
        if ($address) {
            netsh interface portproxy delete v4tov4 listenaddress=$address listenport=$port 2>$null | Out-Null
        }
    }
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port
}

$programDataDir = Join-Path $env:ProgramData "GrowthOS"
New-Item -ItemType Directory -Path $programDataDir -Force | Out-Null
$starterPath = Join-Path $programDataDir "start-model-b.ps1"
$starter = @"
`$ErrorActionPreference = "Continue"
`$command = "nohup bash -c 'exec -a growthos-keepalive sleep infinity' >/dev/null 2>&1 & systemctl start growth-os nginx named 2>/dev/null || true; systemctl is-active growth-os; systemctl is-active nginx; systemctl is-active named 2>/dev/null || true"
wsl -d $Distro -u root -- bash -lc `$command
"@
Set-Content -Path $starterPath -Value $starter -Encoding UTF8

powershell.exe -NoProfile -ExecutionPolicy Bypass -File $starterPath | Out-String | Write-Host

Write-Host "Model B domain exposure hazir."
Write-Host "LAN IPv4: $LanIPv4"
Write-Host "Public IPv4: $PublicIPv4"
Write-Host "WSL IPv4: $wslIp"
Write-Host "Portproxy:"
netsh interface portproxy show v4tov4
Write-Host ""
Write-Host "Modem/router port forwarding gerekli:"
Write-Host "TCP 80  -> $LanIPv4"
Write-Host "TCP 443 -> $LanIPv4"
