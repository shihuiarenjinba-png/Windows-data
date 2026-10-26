[CmdletBinding()]
param(
    [string]$ExePath = '',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $ExePath) { $ExePath = Join-Path $Root 'dist\MSIXAutoBuildIdentity.exe' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Root 'dist\validation' }
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$GuiOutput = Join-Path $OutputDirectory 'gui-1024x768.json'
$PolicyOutput = Join-Path $OutputDirectory 'application-control.json'
$signature = Get-AuthenticodeSignature -LiteralPath $ExePath
$result = [ordered]@{
    schema_version = 1
    exe_path = $ExePath
    exe_sha256 = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash
    authenticode_status = [string]$signature.Status
    requested_gui_size = '1024x768'
    status = 'UNKNOWN'
    exit_code = $null
    gui_report = $GuiOutput
    error = $null
}

try {
    $arguments = 'gui-check --width 1024 --height 768 --output "' + $GuiOutput + '"'
    $process = Start-Process -FilePath $ExePath -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    $result.exit_code = $process.ExitCode
    if ($process.ExitCode -eq 0 -and (Test-Path -LiteralPath $GuiOutput -PathType Leaf)) {
        $gui = Get-Content -Raw -Encoding UTF8 -LiteralPath $GuiOutput | ConvertFrom-Json
        $result.status = if ($gui.status -eq 'PASS') { 'LAUNCHED_GUI_PASS' } else { 'LAUNCHED_GUI_FAIL' }
    } else {
        $result.status = 'LAUNCHED_NO_VALID_GUI_REPORT'
    }
} catch {
    $result.status = 'APPLICATION_CONTROL_BLOCKED'
    $result.error = $_.Exception.Message
}

$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $PolicyOutput -Encoding UTF8
Write-Host ($result | ConvertTo-Json -Depth 5)
if ($result.status -eq 'LAUNCHED_GUI_FAIL' -or $result.status -eq 'LAUNCHED_NO_VALID_GUI_REPORT') { exit 1 }
