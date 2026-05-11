$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=== TurkiyeGundemiApp Windows EXE build v3 ==="

$PythonCandidates = @(
    @("py", "-3.12"),
    @("py", "-3.11")
)

$PythonExe = $null
$PythonArgs = @()

foreach ($Candidate in $PythonCandidates) {
    try {
        $cmd = $Candidate[0]
        $args = $Candidate[1..($Candidate.Count - 1)]
        & $cmd @args --version | Out-Null
        $PythonExe = $cmd
        $PythonArgs = $args
        break
    } catch {}
}

if (-not $PythonExe) {
    throw "Python 3.11 veya 3.12 bulunamadi. python.org uzerinden 64-bit Python 3.12 kurup tekrar deneyin."
}

Write-Host "Python command: $PythonExe $($PythonArgs -join ' ')"

if (Test-Path ".venv") {
    Write-Host "Removing old virtual environment..."
    Remove-Item ".venv" -Recurse -Force
}

Write-Host "Creating virtual environment..."
& $PythonExe @PythonArgs -m venv .venv

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python bulunamadi: $VenvPython"
}

& $VenvPython -m pip install --upgrade pip setuptools wheel
if (Test-Path "requirements.txt") {
    & $VenvPython -m pip install -r requirements.txt
}
& $VenvPython -m pip install "pyinstaller>=6.10,<7"

Write-Host "Running compile check..."
& $VenvPython -m compileall src

Write-Host "Generating static site once..."
& $VenvPython -m src.growth_os.sitegen --site turkiye-gundemi

Write-Host "Cleaning old build output..."
foreach ($Folder in @("build", "dist", "release")) {
    if (Test-Path $Folder) {
        Remove-Item $Folder -Recurse -Force
    }
}

Write-Host "Building recommended onedir executable..."
& $VenvPython -m PyInstaller .\TurkiyeGundemiApp.spec --clean --noconfirm

$DistRoot = Join-Path $Root "dist\TurkiyeGundemiApp"
$Workspace = Join-Path $DistRoot "workspace"

Write-Host "Preparing writable runtime workspace..."
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
foreach ($Folder in @("config", "content", "sites", "docs", "ops", "reports", "tools", "src", ".github")) {
    $Source = Join-Path $Root $Folder
    if (Test-Path $Source) {
        $Target = Join-Path $Workspace $Folder
        if (Test-Path $Target) { Remove-Item $Target -Recurse -Force }
        Copy-Item $Source $Target -Recurse -Force
    }
}

$RunCmd = Join-Path $DistRoot "RUN_TurkiyeGundemiApp.cmd"
@'
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0TurkiyeGundemiApp.exe"
'@ | Set-Content -Path $RunCmd -Encoding ASCII

$DebugCmd = Join-Path $DistRoot "DEBUG_RUN_IN_CONSOLE.cmd"
@'
@echo off
setlocal
cd /d "%~dp0"
echo Starting TurkiyeGundemiApp from:
echo %CD%
echo.
"%~dp0TurkiyeGundemiApp.exe"
echo.
echo Exit code: %ERRORLEVEL%
pause
'@ | Set-Content -Path $DebugCmd -Encoding ASCII

$Exe = Join-Path $DistRoot "TurkiyeGundemiApp.exe"
if (-not (Test-Path $Exe)) {
    throw "EXE uretilemedi: $Exe"
}

Write-Host "Building onefile fallback executable..."
& $VenvPython -m PyInstaller .\TurkiyeGundemiApp-onefile.spec --clean --noconfirm

$OneFile = Join-Path $Root "dist\TurkiyeGundemiApp-onefile.exe"
if (-not (Test-Path $OneFile)) {
    throw "Onefile EXE uretilemedi: $OneFile"
}

New-Item -ItemType Directory -Force -Path "release" | Out-Null

$FolderZip = Join-Path $Root "release\TurkiyeGundemiApp-Windows-x64-folder.zip"
if (Test-Path $FolderZip) { Remove-Item $FolderZip -Force }
Compress-Archive -Path "dist\TurkiyeGundemiApp" -DestinationPath $FolderZip

$FinalZip = Join-Path $Root "release\TurkiyeGundemiApp-Windows-x64-final.zip"
if (Test-Path $FinalZip) { Remove-Item $FinalZip -Force }
Compress-Archive -Path @("dist\TurkiyeGundemiApp", "dist\TurkiyeGundemiApp-onefile.exe") -DestinationPath $FinalZip

Copy-Item $OneFile (Join-Path $Root "release\TurkiyeGundemiApp-onefile.exe") -Force

Write-Host ""
Write-Host "Build tamamlandi."
Write-Host "ONERILEN KLASOR EXE:"
Write-Host "  $Exe"
Write-Host "ONERILEN ZIP:"
Write-Host "  $FolderZip"
Write-Host "TEK DOSYA ALTERNATIF:"
Write-Host "  $OneFile"
Write-Host "FINAL ZIP:"
Write-Host "  $FinalZip"
Write-Host ""
Write-Host "Not: folder.zip tamamen ayiklanmadan exe calistirmayin. Zip icinden cift tiklamak embedded Python hatasi verebilir."
