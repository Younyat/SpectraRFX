param(
    [string]$RadioCondaPythonPath = "C:\Users\Usuario\radioconda\python.exe",
    [string]$BackendPythonPath = "",
    [string]$RemoteUser = "assouyat",
    [string]$RemoteHost = "192.168.193.49",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$AppSyncIntervalMs = 5000,
    [int]$SpectrumPollIntervalMs = 100,
    [int]$WaterfallPollIntervalMs = 100,
    # Real BLE decode of Live Monitor's live burst (see BLE-RFFI Studio
    # README's "Live BLE decode" section) -- on by default so it never has
    # to be set by hand in the terminal, but shown here explicitly so it is
    # visible/overridable directly on the main command line.
    [object]$EnableBleLiveDecode = $true,
    # Experimental AI Model Research Plugin -- same on-by-default-here
    # convenience as EnableBleLiveDecode above, so the existing startup
    # command keeps working unchanged. Pass -EnableAiResearchPlugin $false
    # to turn it back off.
    [object]$EnableAiResearchPlugin = $true
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path $PSScriptRoot
$Runner = Join-Path $RootDir "scripts\run_dev.ps1"
$ValidatedBackendPython = Join-Path $RootDir "backend\.venv-validation\Scripts\python.exe"

# Keep one simple public command. The normal backend needs FastAPI + Bleak,
# while radioconda remains the isolated GNU Radio/UHD runtime for the B200.
# Prefer the already validated backend interpreter when present; run_dev.ps1
# uses it as the base for backend\venv and installs the declared requirements.
if (-not $BackendPythonPath -and (Test-Path -LiteralPath $ValidatedBackendPython)) {
    $BackendPythonPath = $ValidatedBackendPython
}

if (-not (Test-Path $Runner)) {
    throw "No se encontro scripts\run_dev.ps1"
}

& $Runner `
    -UseRealSdr 1 `
    -BackendPythonPath $BackendPythonPath `
    -RadioCondaPythonPath $RadioCondaPythonPath `
    -RemoteUser $RemoteUser `
    -RemoteHost $RemoteHost `
    -BackendPort $BackendPort `
    -FrontendHost $FrontendHost `
    -AppSyncIntervalMs $AppSyncIntervalMs `
    -SpectrumPollIntervalMs $SpectrumPollIntervalMs `
    -WaterfallPollIntervalMs $WaterfallPollIntervalMs `
    -EnableBleLiveDecode $EnableBleLiveDecode `
    -EnableAiResearchPlugin $EnableAiResearchPlugin
