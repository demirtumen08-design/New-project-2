$ErrorActionPreference = "Stop"

$currentUser = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentUser)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    $script = $MyInvocation.MyCommand.Path
    Start-Process powershell -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$script`""
    )
    Write-Output "Yonetici yetkisi istendi. UAC penceresini onaylayin."
    exit 0
}

$vmName = "TurkiyeGundemi-ModelB"
$vmDir = Join-Path $env:USERPROFILE "VirtualBox VMs\$vmName"
$isoDir = Join-Path $env:USERPROFILE "Downloads"
$isoPath = Join-Path $isoDir "ubuntu-24.04.3-live-server-amd64.iso"
$isoUrl = "https://releases.ubuntu.com/24.04.3/ubuntu-24.04.3-live-server-amd64.iso"

if (-not (Get-Command VBoxManage.exe -ErrorAction SilentlyContinue)) {
    Write-Output "VirtualBox yukleniyor..."
    winget install --id Oracle.VirtualBox --exact --accept-package-agreements --accept-source-agreements
}

$vbox = (Get-Command VBoxManage.exe -ErrorAction Stop).Source

if (-not (Test-Path $isoPath)) {
    Write-Output "Ubuntu Server ISO indiriliyor: $isoUrl"
    Invoke-WebRequest -Uri $isoUrl -OutFile $isoPath
}

if (-not (Test-Path $vmDir)) {
    & $vbox createvm --name $vmName --ostype Ubuntu_64 --basefolder (Split-Path $vmDir) --register
    & $vbox modifyvm $vmName --memory 4096 --cpus 2 --graphicscontroller vmsvga --nic1 bridged
    & $vbox createhd --filename (Join-Path $vmDir "$vmName.vdi") --size 40960 --format VDI
    & $vbox storagectl $vmName --name "SATA" --add sata --controller IntelAhci
    & $vbox storageattach $vmName --storagectl "SATA" --port 0 --device 0 --type hdd --medium (Join-Path $vmDir "$vmName.vdi")
    & $vbox storageattach $vmName --storagectl "SATA" --port 1 --device 0 --type dvddrive --medium $isoPath
}

Write-Output "VirtualBox VM hazir: $vmName"
Write-Output "VM'i baslatip Ubuntu Server kurulumunu tamamlayin:"
Write-Output "VBoxManage startvm `"$vmName`""
Write-Output "Kurulumda network icin bridged adapter kullanin ve Linux'a sabit LAN IP verin."
