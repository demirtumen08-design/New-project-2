param(
  [string]$Distro = "Ubuntu",
  [string]$PublicIp = "213.14.161.140",
  [switch]$AddLocalHosts
)

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Error "Bu betiği Yönetici olarak açılmış PowerShell içinde çalıştırın."
}

$wslIp = (wsl -d $Distro -- bash -lc "hostname -I | awk '{print `$1}'").Trim()
if (-not $wslIp) {
  Write-Error "WSL IP adresi bulunamadı. Önce Ubuntu/WSL ve Growth OS servislerini çalıştırın."
}

Write-Host "WSL IP: $wslIp"
Write-Host "Public IP: $PublicIp"

foreach ($port in 80, 443) {
  netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null | Out-Null
  netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$wslIp connectport=$port | Out-Null
}

$rules = @(
  @{ Name = "Turkiye Gundemi HTTP"; Port = 80 },
  @{ Name = "Turkiye Gundemi HTTPS"; Port = 443 }
)

foreach ($rule in $rules) {
  $existing = Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue
  if ($existing) {
    Set-NetFirewallRule -DisplayName $rule.Name -Enabled True -Direction Inbound -Action Allow | Out-Null
    Get-NetFirewallRule -DisplayName $rule.Name | Set-NetFirewallPortFilter -Protocol TCP -LocalPort $rule.Port | Out-Null
  } else {
    New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $rule.Port | Out-Null
  }
}

Write-Host ""
Write-Host "Portproxy:"
netsh interface portproxy show all

Write-Host ""
Write-Host "Kontrol:"
try {
  $public = (Invoke-WebRequest -UseBasicParsing -Uri "https://api.ipify.org" -TimeoutSec 10).Content.Trim()
  Write-Host "Dış IP: $public"
} catch {
  Write-Warning "Dış IP okunamadı: $($_.Exception.Message)"
}

try {
  $home = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1/" -TimeoutSec 10
  Write-Host "Yerel site HTTP: $($home.StatusCode)"
} catch {
  Write-Warning "Yerel site kontrolü başarısız: $($_.Exception.Message)"
}

Write-Host ""
if ($AddLocalHosts) {
  $hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
  $hosts = Get-Content -Raw -Path $hostsPath
  $block = @"

# Turkiye Gundemi local development access
127.0.0.1 turkiyegundemi.com
127.0.0.1 www.turkiyegundemi.com
"@
  if ($hosts -notmatch "turkiyegundemi\.com") {
    Add-Content -Path $hostsPath -Value $block
    ipconfig /flushdns | Out-Null
    Write-Host "Yerel hosts kaydı eklendi: turkiyegundemi.com -> 127.0.0.1"
  } else {
    Write-Host "Hosts dosyasında turkiyegundemi.com kaydı zaten var; elle kontrol edin: $hostsPath"
  }
  Write-Host ""
}

Write-Host ""
Write-Host "Natro DNS kayıtları:"
Write-Host "@    A    $PublicIp"
Write-Host "www  A    $PublicIp"
