[CmdletBinding()]
param([switch]$SkipInstall)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Root

python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }

if (-not $SkipInstall) {
    python -m pip install --requirement requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
}

python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name MSIXAutoBuildIdentity `
    --distpath (Join-Path $Root 'dist') `
    --workpath (Join-Path $Root 'build') `
    --specpath (Join-Path $Root 'build') `
    (Join-Path $Root 'run.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$Exe = Join-Path $Root 'dist\MSIXAutoBuildIdentity.exe'
if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw 'Expected EXE was not created.' }
$Hash = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash
Set-Content -LiteralPath ($Exe + '.sha256') -Value ($Hash + '  MSIXAutoBuildIdentity.exe') -Encoding ASCII
Write-Host "Built: $Exe"
Write-Host "SHA256: $Hash"
