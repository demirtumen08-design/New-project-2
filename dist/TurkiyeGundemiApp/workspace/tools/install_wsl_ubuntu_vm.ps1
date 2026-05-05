$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir "wsl-install.log"

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    $script = $MyInvocation.MyCommand.Path
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$script`""
    )
    Write-Output "Yonetici yetkisi istendi. UAC penceresini onaylayin."
    exit 0
}

Start-Transcript -Path $LogPath -Append | Out-Null
Write-Output "WSL ve sanal makine altyapisi aciliyor..."
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
wsl --install --no-distribution

$wslConfig = @"
[wsl2]
memory=4GB
processors=2
localhostForwarding=true
networkingMode=nat
dnsTunneling=true
firewall=true
"@
$wslConfigPath = Join-Path $env:USERPROFILE ".wslconfig"
$wslConfig | Set-Content -Path $wslConfigPath -Encoding ASCII

try {
    wsl --set-default-version 2
} catch {
    Write-Output "WSL default version simdi ayarlanamadi; reboot sonrasi tekrar denenebilir."
}

Write-Output ""
Write-Output "Ilk asama tamam."
Write-Output "Simdi Windows'u yeniden baslatin."
Write-Output "Yeniden baslattiktan sonra bu komutu calistirin:"
Write-Output "powershell -ExecutionPolicy Bypass -File .\tools\provision_wsl_model_b.ps1"
Stop-Transcript | Out-Null
