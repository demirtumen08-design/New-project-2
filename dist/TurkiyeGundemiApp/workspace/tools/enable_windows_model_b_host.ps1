param(
    [string]$Distro = "Ubuntu",
    [string]$TaskName = "GrowthOS-Start-ModelB",
    [switch]$SkipFirewall,
    [switch]$SkipTask
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
        "-Distro", "`"$Distro`"",
        "-TaskName", "`"$TaskName`""
    )
    if ($SkipFirewall) { $args += "-SkipFirewall" }
    if ($SkipTask) { $args += "-SkipTask" }
    Start-Process -FilePath "powershell.exe" -ArgumentList $args -Verb RunAs -Wait
    exit $LASTEXITCODE
}

$programDataDir = Join-Path $env:ProgramData "GrowthOS"
New-Item -ItemType Directory -Path $programDataDir -Force | Out-Null

if (-not $SkipFirewall) {
    $rules = @(
        @{ Name = "GrowthOS-HTTP-80"; Display = "Growth OS HTTP 80"; Protocol = "TCP"; Port = "80" },
        @{ Name = "GrowthOS-HTTPS-443"; Display = "Growth OS HTTPS 443"; Protocol = "TCP"; Port = "443" },
        @{ Name = "GrowthOS-DNS-TCP-53"; Display = "Growth OS DNS TCP 53"; Protocol = "TCP"; Port = "53" },
        @{ Name = "GrowthOS-DNS-UDP-53"; Display = "Growth OS DNS UDP 53"; Protocol = "UDP"; Port = "53" }
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

    $wslCreator = Get-NetFirewallHyperVVMCreator -ErrorAction SilentlyContinue |
        Where-Object { $_.FriendlyName -eq "WSL" } |
        Select-Object -First 1

    if ($wslCreator) {
        Set-NetFirewallHyperVVMSetting `
            -Name $wslCreator.VMCreatorId `
            -Enabled True `
            -DefaultInboundAction Allow `
            -LoopbackEnabled True | Out-Null

        foreach ($rule in $rules) {
            $hyperVName = "$($rule.Name)-WSL"
            if (-not (Get-NetFirewallHyperVRule -Name $hyperVName -ErrorAction SilentlyContinue)) {
                New-NetFirewallHyperVRule `
                    -Name $hyperVName `
                    -DisplayName "$($rule.Display) for WSL" `
                    -VMCreatorId $wslCreator.VMCreatorId `
                    -Direction Inbound `
                    -Action Allow `
                    -Protocol $rule.Protocol `
                    -LocalPorts $rule.Port `
                    -Enabled True | Out-Null
            }
        }
    }

    foreach ($port in @("80", "443", "53")) {
        netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null | Out-Null
    }
}

$starterPath = Join-Path $programDataDir "start-model-b.ps1"
$starter = @"
`$ErrorActionPreference = "Continue"
wsl -d $Distro -u root -- bash -lc "systemctl start growth-os nginx named 2>/dev/null || true; systemctl is-active growth-os; systemctl is-active nginx; systemctl is-active named 2>/dev/null || true"
"@
Set-Content -Path $starterPath -Value $starter -Encoding UTF8

if (-not $SkipTask) {
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$starterPath`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
        -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
}

powershell.exe -NoProfile -ExecutionPolicy Bypass -File $starterPath | Out-String | Write-Host

Write-Host "Windows host rules are ready."
Write-Host "Startup task: $TaskName"
Write-Host "Starter: $starterPath"
