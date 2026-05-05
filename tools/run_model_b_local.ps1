$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:GROWTH_OS_ROOT = $Root
$env:GROWTH_OS_SITE_AT_ROOT = "1"
$env:GROWTH_OS_ADMIN_USER = "admin"
if (-not $env:GROWTH_OS_ADMIN_PASSWORD) {
    $env:GROWTH_OS_ADMIN_PASSWORD = "admin12345"
}

python -m src.growth_os.sitegen --site turkiye-gundemi
python -m src.growth_os.server --host 127.0.0.1 --port 8090 --site-at-root
