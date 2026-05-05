$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Wsl($Command) {
    wsl -d Ubuntu -u root -- bash -lc $Command
}

function ConvertTo-WslPath($Path) {
    $resolved = (Resolve-Path $Path).Path
    $drive = $resolved.Substring(0,1).ToLower()
    $rest = $resolved.Substring(2).Replace('\','/')
    return "/mnt/$drive$rest"
}

$listRaw = (& wsl --list --quiet 2>$null) -join "`n"
$list = $listRaw -replace "`0", ""
if ($list -notmatch "(?m)^Ubuntu$") {
    Write-Output "Ubuntu WSL kuruluyor. Ilk acilista Linux kullanici adi/parola sorabilir."
    wsl --install -d Ubuntu
    Write-Output "Ubuntu kurulumu baslatildi. Eger pencere kullanici adi/parola isterse tamamlayin, sonra bu scripti tekrar calistirin."
    exit 0
}

wsl --set-version Ubuntu 2

Write-Output "WSL systemd ayari yapiliyor..."
Invoke-Wsl "cat >/etc/wsl.conf <<'EOF'
[boot]
systemd=true

[user]
default=root
EOF"
wsl --shutdown
Start-Sleep -Seconds 3

Write-Output "Ubuntu paketleri hazirlaniyor..."
Invoke-Wsl "sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git rsync python3 python3-venv python3-pip nginx bind9 bind9utils dnsutils certbot python3-certbot-nginx"

Write-Output "Proje WSL icine kopyalaniyor..."
Invoke-Wsl "mkdir -p ~/growth-os"
wsl -d Ubuntu -- bash -lc "rm -rf ~/growth-os/*"
$wslProjectPath = ConvertTo-WslPath $Root
wsl -d Ubuntu -u root -- bash -lc "cp -R '$wslProjectPath'/* ~/growth-os/"

Write-Output "Model B kuruluyor..."
Invoke-Wsl "cd ~/growth-os && DOMAIN=turkiyegundemi.com bash ops/install_model_b.sh"

Write-Output "Windows firewall, WSL firewall ve acilis gorevi ayarlaniyor..."
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "enable_windows_model_b_host.ps1")

Write-Output ""
Write-Output "WSL Model B hazir."
Write-Output "Site: http://127.0.0.1/"
Write-Output "Admin: http://127.0.0.1/admin"
Write-Output "Durum: wsl -d Ubuntu -- systemctl status growth-os"
