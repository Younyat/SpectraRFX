param(
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [string]$RemoteUser = "",
    [string]$RemoteHost = "",
    [string]$RemoteVenvActivate = "",
    [int]$AppSyncIntervalMs = 5000,
    [int]$SpectrumPollIntervalMs = 100,
    [int]$WaterfallPollIntervalMs = 100,
    [bool]$InstallDeps = $true,
    [bool]$InstallTools = $true,
    [bool]$FullBackendDeps = $false,
    [string]$BackendPythonPath = "",
    [string]$RadioCondaPythonPath = "C:\Users\Usuario\radioconda\python.exe",
    [object]$UseRealSdr = $false,
    [object]$EnableBleIqCapture = $true,
    [object]$EnableBleReplay = $true,
    [object]$EnableBleOfflineIqAnalysis = $true,
    [object]$EnableBleLiveDecode = $true,
    # Experimental AI Model Research Plugin (import a pretrained ONNX model,
    # run isolated research inference over preserved RF captures). On by
    # default here for the same reason as EnableBleLiveDecode above: so the
    # main startup command always enables it without requiring
    # $env:AI_RESEARCH_PLUGIN_ENABLED / $env:VITE_AI_RESEARCH_PLUGIN_ENABLED
    # to be set by hand. Still overridable via -EnableAiResearchPlugin $false
    # or runtime_settings.json. The plugin itself remains off by default at
    # the platform-code level (backend module.py / frontend runtime.ts) --
    # this default only affects this convenience launcher.
    [object]$EnableAiResearchPlugin = $true
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$VenvDir = Join-Path $BackendDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$FilteredRequirements = Join-Path $BackendDir "requirements.dev-windows.txt"
$RuntimeSettingsPath = Join-Path $BackendDir "app\infrastructure\persistence\storage\config\runtime_settings.json"
$RuntimeSettingsValues = $null

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Convert-ToBool {
    param([object]$Value)

    if ($Value -is [bool]) {
        return $Value
    }

    $Text = "$Value".Trim().ToLowerInvariant()
    return $Text -in @("1", "true", "`$true", "yes", "y", "on")
}

function Load-RuntimeSettings {
    if (-not (Test-Path -LiteralPath $RuntimeSettingsPath)) {
        return $null
    }
    try {
        $Data = Get-Content -LiteralPath $RuntimeSettingsPath -Raw | ConvertFrom-Json
        return $Data.values
    } catch {
        Write-Host "No se pudo leer runtime_settings.json; se usaran parametros del script y defaults." -ForegroundColor Yellow
        return $null
    }
}

function Get-RuntimeSetting {
    param(
        [string]$Name,
        [object]$Fallback
    )

    if ($RuntimeSettingsValues -and ($RuntimeSettingsValues.PSObject.Properties.Name -contains $Name)) {
        $Value = $RuntimeSettingsValues.$Name
        if ($null -ne $Value -and "$Value" -ne "") {
            return $Value
        }
    }

    return $Fallback
}

function Get-CommandPath {
    param([string[]]$Names)

    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }

    return $null
}

function Test-WindowsAppsPython {
    param([string]$Path)
    return ($Path -like "*\WindowsApps\PythonSoftwareFoundation.Python*")
}

function Install-WithWinget {
    param(
        [string]$Id,
        [string]$Name
    )

    if (-not (Test-Command "winget")) {
        throw "No se encontro $Name y no esta disponible winget para instalarlo automaticamente."
    }

    Write-Step "Installing $Name with winget"
    Invoke-Native `
        -FilePath "winget" `
        -ArgumentList @("install", "--id", $Id, "--exact", "--accept-package-agreements", "--accept-source-agreements") `
        -ErrorMessage "No se pudo instalar $Name con winget."
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$ErrorMessage
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw $ErrorMessage
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }

    $Children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($Child in $Children) {
        Stop-ProcessTree -ProcessId ([int]$Child.ProcessId)
    }

    $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($Process) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ListeningProcessIds {
    param([int]$Port)
    $Ids = @()
    foreach ($Line in (netstat -ano -p tcp 2>$null)) {
        if ($Line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            $Ids += [int]$Matches[1]
        }
    }
    return @($Ids | Select-Object -Unique)
}

function Stop-StaleSpectrumBackend {
    param([int]$Port)
    $Listeners = @(Get-ListeningProcessIds -Port $Port)
    if (-not $Listeners.Count) { return }

    $IsSpectrumLab = $false
    try {
        $OpenApi = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/openapi.json" -TimeoutSec 3
        $Paths = @($OpenApi.paths.PSObject.Properties.Name)
        $IsSpectrumLab = (
            $OpenApi.info.title -eq "Spectrum Lab" -and
            $Paths -contains "/api/ble/capture/devices" -and
            $Paths -contains "/api/ble/hybrid/sessions"
        )
    } catch {}

    # If a previous unified launcher is already shutting down, its listener
    # can remain visible briefly after the HTTP server stops answering. Give
    # that known race time to finish before classifying the port as foreign.
    if (-not $IsSpectrumLab) {
        $ShutdownDeadline = (Get-Date).AddSeconds(5)
        while ((Get-ListeningProcessIds -Port $Port).Count -and (Get-Date) -lt $ShutdownDeadline) {
            Start-Sleep -Milliseconds 250
        }
        if (-not (Get-ListeningProcessIds -Port $Port).Count) { return }
    }

    if (-not $IsSpectrumLab) {
        throw "El puerto $Port esta ocupado por otro servicio. Cierre ese servicio o use -BackendPort con otro puerto."
    }
    Write-Host "Deteniendo backend Spectrum Lab anterior en el puerto $Port (PID: $($Listeners -join ', '))." -ForegroundColor Yellow
    foreach ($Id in $Listeners) { Stop-ProcessTree -ProcessId $Id }
    $Deadline = (Get-Date).AddSeconds(10)
    while ((Get-ListeningProcessIds -Port $Port).Count -and (Get-Date) -lt $Deadline) { Start-Sleep -Milliseconds 250 }
    if ((Get-ListeningProcessIds -Port $Port).Count) { throw "No se pudo liberar el puerto $Port." }
}

function Stop-StaleSpectrumFrontend {
    param([int]$Port = 5173)

    $Listeners = @(Get-ListeningProcessIds -Port $Port)
    if (-not $Listeners.Count) { return }

    $IsSpectrumLab = $false
    try {
        $Response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3
        $IsSpectrumLab = $Response.Content -match "Spectrum Lab - RF Signal Analyzer"
    } catch {}

    if (-not $IsSpectrumLab) {
        throw "El puerto $Port esta ocupado por otra interfaz. Cierre ese servicio antes de iniciar Spectrum Lab."
    }

    Write-Host "Deteniendo frontend Spectrum Lab anterior en el puerto $Port (PID: $($Listeners -join ', '))." -ForegroundColor Yellow
    foreach ($Id in $Listeners) { Stop-ProcessTree -ProcessId $Id }
    $Deadline = (Get-Date).AddSeconds(10)
    while ((Get-ListeningProcessIds -Port $Port).Count -and (Get-Date) -lt $Deadline) { Start-Sleep -Milliseconds 250 }
    if ((Get-ListeningProcessIds -Port $Port).Count) { throw "No se pudo liberar el puerto $Port." }
}

function Get-PythonVersion {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $Output = & $FilePath @($ArgumentList + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")) 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $Output) {
        return $null
    }

    try {
        return [version]($Output | Select-Object -First 1)
    } catch {
        return $null
    }
}

function Test-Python310 {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $Version = Get-PythonVersion -FilePath $FilePath -ArgumentList $ArgumentList
    return ($Version -and $Version -ge [version]"3.10.0")
}

function Get-CompatiblePython {
    if ($BackendPythonPath) {
        if (-not (Test-Path $BackendPythonPath)) {
            throw "No se encontro BackendPythonPath: $BackendPythonPath"
        }
        if (-not (Test-Python310 -FilePath $BackendPythonPath)) {
            throw "BackendPythonPath debe ser Python 3.10+: $BackendPythonPath"
        }
        return @{ FilePath = $BackendPythonPath; Args = @() }
    }

    $Candidates = @()

    $CommonPythonPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python310\python.exe")
    )

    if (${env:ProgramFiles(x86)}) {
        $CommonPythonPaths += @(
            (Join-Path ${env:ProgramFiles(x86)} "Python312\python.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Python311\python.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Python310\python.exe")
        )
    }

    foreach ($Path in $CommonPythonPaths) {
        if (Test-Path $Path) {
            $Candidates += @{ FilePath = $Path; Args = @() }
        }
    }

    if (Test-Command "py") {
        $Candidates += @{ FilePath = "py"; Args = @("-3.12") }
        $Candidates += @{ FilePath = "py"; Args = @("-3.11") }
        $Candidates += @{ FilePath = "py"; Args = @("-3.10") }
    }

    $PythonCommandPath = Get-CommandPath -Names @("python.exe", "python")
    if ($PythonCommandPath -and -not (Test-WindowsAppsPython -Path $PythonCommandPath)) {
        $Candidates += @{ FilePath = $PythonCommandPath; Args = @() }
    }

    foreach ($Candidate in $Candidates) {
        if (Test-Python310 -FilePath $Candidate.FilePath -ArgumentList $Candidate.Args) {
            return $Candidate
        }
    }

    if ($InstallTools) {
        Install-WithWinget -Id "Python.Python.3.12" -Name "Python 3.12"
        $CandidatesAfterInstall = @()

        foreach ($Path in $CommonPythonPaths) {
            if (Test-Path $Path) {
                $CandidatesAfterInstall += @{ FilePath = $Path; Args = @() }
            }
        }

        if (Test-Command "py") {
            $CandidatesAfterInstall += @{ FilePath = "py"; Args = @("-3.12") }
        }
        $PythonCommandPathAfterInstall = Get-CommandPath -Names @("python.exe", "python")
        if ($PythonCommandPathAfterInstall -and -not (Test-WindowsAppsPython -Path $PythonCommandPathAfterInstall)) {
            $CandidatesAfterInstall += @{ FilePath = $PythonCommandPathAfterInstall; Args = @() }
        }
        foreach ($Candidate in $CandidatesAfterInstall) {
            if (Test-Python310 -FilePath $Candidate.FilePath -ArgumentList $Candidate.Args) {
                return $Candidate
            }
        }
    }

    throw "No se encontro Python 3.10+. Instala Python 3.10 o superior, cierra PowerShell y vuelve a ejecutar el script."
}

function New-FilteredRequirements {
    $ExcludedPackages = @("gnuradio", "uhd", "pyrtlsdr")
    $Lines = Get-Content (Join-Path $BackendDir "requirements.txt") | Where-Object {
        $Line = $_.Trim()
        if ($Line -eq "" -or $Line.StartsWith("#")) {
            return $true
        }

        foreach ($Package in $ExcludedPackages) {
            if ($Line -match "(?i)^$Package([<>=!~ ]|$)") {
                return $false
            }
        }

        return $true
    }

    $Lines | Set-Content -Path $FilteredRequirements -Encoding ASCII
    return $FilteredRequirements
}

function Ensure-Tools {
    Write-Step "Checking tools"

    $script:PythonCommand = Get-CompatiblePython

    if (-not (Test-Command "node")) {
        if ($InstallTools) {
            Install-WithWinget -Id "OpenJS.NodeJS.LTS" -Name "Node.js"
        } else {
            throw "Node.js no encontrado. Instala Node.js 18+."
        }
    }

    if (-not (Test-Command "npm")) {
        throw "npm no encontrado. Cierra y abre PowerShell despues de instalar Node.js, y vuelve a ejecutar este script."
    }
}

Ensure-Tools

$RuntimeSettingsValues = Load-RuntimeSettings
if ($RuntimeSettingsValues) {
    Write-Host "Runtime settings loaded: $RuntimeSettingsPath" -ForegroundColor DarkCyan
}

$RadioCondaPythonPath = [string](Get-RuntimeSetting -Name "RADIOCONDA_PYTHON" -Fallback $RadioCondaPythonPath)
$AppSyncIntervalMs = [int](Get-RuntimeSetting -Name "VITE_APP_SYNC_INTERVAL_MS" -Fallback $AppSyncIntervalMs)
$SpectrumPollIntervalMs = [int](Get-RuntimeSetting -Name "VITE_SPECTRUM_POLL_INTERVAL_MS" -Fallback $SpectrumPollIntervalMs)
$WaterfallPollIntervalMs = [int](Get-RuntimeSetting -Name "VITE_WATERFALL_POLL_INTERVAL_MS" -Fallback $WaterfallPollIntervalMs)
$EnableBleIqCapture = Get-RuntimeSetting -Name "BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED" -Fallback $EnableBleIqCapture
$EnableBleReplay = Get-RuntimeSetting -Name "BLE_ANALYZER_V1" -Fallback $EnableBleReplay
$EnableBleOfflineIqAnalysis = Get-RuntimeSetting -Name "BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED" -Fallback $EnableBleOfflineIqAnalysis
$EnableBleLiveDecode = Get-RuntimeSetting -Name "BLE_LIVE_DECODE_ENABLED" -Fallback $EnableBleLiveDecode
$EnableAiResearchPlugin = Get-RuntimeSetting -Name "AI_RESEARCH_PLUGIN_ENABLED" -Fallback $EnableAiResearchPlugin

foreach ($RuntimeEnvKey in @(
    "UHD_DEVICE_ARGS",
    "DEFAULT_ANTENNA",
    "DEFAULT_CENTER_FREQUENCY_HZ",
    "DEFAULT_SAMPLE_RATE_HZ",
    "DEFAULT_SPAN_HZ",
    "DEFAULT_GAIN_DB",
    "DEFAULT_RBW_HZ",
    "DEFAULT_VBW_HZ",
    "DEFAULT_REFERENCE_LEVEL_DB",
    "DEFAULT_NOISE_FLOOR_OFFSET_DB",
    "DEFAULT_AVERAGING_FACTOR",
    "DEFAULT_SMOOTHING_FACTOR",
    "DEFAULT_WATERFALL_HISTORY_SIZE",
    "DEFAULT_RECORDING_DURATION_SECONDS",
    "DEFAULT_FM_DEVIATION_HZ",
    "DEFAULT_AUDIO_SAMPLE_RATE_HZ",
    "RF_MIN_CENTER_FREQUENCY_HZ",
    "RF_MAX_CENTER_FREQUENCY_HZ",
    "RF_MIN_SAMPLE_RATE_HZ",
    "RF_MAX_SAMPLE_RATE_HZ",
    "RF_MAX_SPAN_HZ",
    "RF_MIN_GAIN_DB",
    "RF_MAX_GAIN_DB",
    "RF_MIN_RBW_HZ",
    "RF_MAX_RBW_HZ",
    "RF_MIN_VBW_HZ",
    "RF_MAX_VBW_HZ",
    "REAL_SDR_FPS",
    "REAL_SDR_MAX_FFT_SIZE",
    "REAL_SDR_CONNECT_TIMEOUT",
    "QC_MIN_VALID_SNR_DB",
    "QC_MAX_VALID_CLIPPING_PCT",
    "QC_MAX_SILENCE_PCT",
    "RF_INTELLIGENCE_THRESHOLD_OFFSET_DB",
    "RF_INTELLIGENCE_MIN_SNR_DB"
)) {
    $RuntimeValue = Get-RuntimeSetting -Name $RuntimeEnvKey -Fallback $null
    if ($null -ne $RuntimeValue) {
        Set-Item -Path "Env:$RuntimeEnvKey" -Value "$RuntimeValue"
    }
}

Write-Step "Preparing backend"
$UseProvidedBackendRuntime = $false
if ($BackendPythonPath -and (Test-Path -LiteralPath $BackendPythonPath)) {
    $VenvPython = (Resolve-Path -LiteralPath $BackendPythonPath).Path
    $VenvDir = Split-Path -Parent (Split-Path -Parent $VenvPython)
    $UseProvidedBackendRuntime = $true
    Write-Host "Usando runtime backend validado: $VenvPython" -ForegroundColor Green
}
$ExistingVenvVersion = $null
$VenvConfigPath = Join-Path $VenvDir "pyvenv.cfg"
$ExistingVenvUsesWindowsApps = $false
if (Test-Path $VenvPython) {
    $ExistingVenvVersion = Get-PythonVersion -FilePath $VenvPython
}
if (Test-Path -LiteralPath $VenvConfigPath) {
    $ExistingVenvUsesWindowsApps = [bool]((Get-Content -LiteralPath $VenvConfigPath -Raw) -match "WindowsApps")
}

if ((Test-Path $VenvPython) -and ($ExistingVenvUsesWindowsApps -or -not $ExistingVenvVersion -or $ExistingVenvVersion -lt [version]"3.10.0")) {
    $VersionLabel = if ($ExistingVenvUsesWindowsApps) { "Microsoft Store/WindowsApps no portable" } elseif ($ExistingVenvVersion) { "$ExistingVenvVersion" } else { "invalido" }
    Write-Host "El entorno virtual existente usa Python $VersionLabel. Se va a recrear: $VenvDir" -ForegroundColor Yellow
    # Release imported .pyd files before removing the environment. The normal
    # startup cleanup later is intentionally idempotent.
    Stop-StaleSpectrumBackend -Port $BackendPort
    Stop-StaleSpectrumFrontend -Port 5173
    $ResolvedVenv = (Resolve-Path -LiteralPath $VenvDir).Path
    $ResolvedBackend = (Resolve-Path -LiteralPath $BackendDir).Path
    if (-not $ResolvedVenv.StartsWith($ResolvedBackend + [IO.Path]::DirectorySeparatorChar)) {
        throw "Se rechazo eliminar un entorno virtual fuera del backend: $ResolvedVenv"
    }
    Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
}

if (-not (Test-Path $VenvDir)) {
    Invoke-Native `
        -FilePath $PythonCommand.FilePath `
        -ArgumentList @($PythonCommand.Args + @("-m", "venv", $VenvDir)) `
        -ErrorMessage "No se pudo crear el entorno virtual del backend."
}

if (-not (Test-Path $VenvPython)) {
    throw "No se encontro Python dentro del entorno virtual: $VenvPython"
}

if ($InstallDeps -and -not $UseProvidedBackendRuntime) {
    Invoke-Native `
        -FilePath $VenvPython `
        -ArgumentList @("-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools<82") `
        -ErrorMessage "No se pudo actualizar pip/wheel/setuptools<82."

    if ($FullBackendDeps) {
        $RequirementsPath = Join-Path $BackendDir "requirements.txt"
    } else {
        $RequirementsPath = New-FilteredRequirements
        Write-Host "Modo desarrollo Windows: se omiten gnuradio, uhd y pyrtlsdr. Usa -FullBackendDeps `$true si tienes SDR/hardware configurado." -ForegroundColor Yellow
    }

    Invoke-Native `
        -FilePath $VenvPython `
        -ArgumentList @("-m", "pip", "install", "-r", $RequirementsPath) `
        -ErrorMessage "No se pudieron instalar las dependencias del backend."
} elseif ($UseProvidedBackendRuntime) {
    & $VenvPython -c "import fastapi, uvicorn, bleak; print('Runtime backend validado: FastAPI + Uvicorn + Bleak')"
    if ($LASTEXITCODE -ne 0) {
        throw "BackendPythonPath no contiene las dependencias backend validadas."
    }
}

Write-Step "Preparing frontend"
if ($InstallDeps) {
    Push-Location $FrontendDir
    try {
        Invoke-Native -FilePath "npm" -ArgumentList @("install") -ErrorMessage "No se pudieron instalar las dependencias del frontend."
    } finally {
        Pop-Location
    }
}

Write-Step "Starting backend on http://localhost:$BackendPort"
# Stop the backend first. Its unified launcher will then stop its own Vite
# child. Doing this in the opposite order creates a race where the old
# launcher shuts down port 8000 while this new launcher is identifying it.
Stop-StaleSpectrumBackend -Port $BackendPort
Stop-StaleSpectrumFrontend -Port 5173
if ($RadioCondaPythonPath) {
    $env:RADIOCONDA_PYTHON = $RadioCondaPythonPath
}
$UseRealSdrEnabled = Convert-ToBool $UseRealSdr
if ($UseRealSdrEnabled) {
    $env:USE_REAL_SDR = "1"
} else {
    $env:USE_REAL_SDR = "0"
}
$env:BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED = if (Convert-ToBool $EnableBleIqCapture) { "true" } else { "false" }
$env:BLE_ANALYZER_V1 = if (Convert-ToBool $EnableBleReplay) { "true" } else { "false" }
$env:BLE_IQ_OFFLINE_EXPERIMENTAL_ENABLED = if (Convert-ToBool $EnableBleOfflineIqAnalysis) { "true" } else { "false" }
# Real BLE decode of Live Monitor's live burst (see BLE-RFFI Studio README's
# "Live BLE decode" section) -- on by default here so the main startup
# command always enables it, instead of requiring $env:BLE_LIVE_DECODE_ENABLED
# to be set by hand in the same terminal every time. Still overridable via
# -EnableBleLiveDecode $false or runtime_settings.json if it ever needs to be
# turned off again.
$env:BLE_LIVE_DECODE_ENABLED = if (Convert-ToBool $EnableBleLiveDecode) { "true" } else { "false" }
$env:BLE_CAPTURE_AND_DECODE_ENABLED = "false"
$env:AI_RESEARCH_PLUGIN_ENABLED = if (Convert-ToBool $EnableAiResearchPlugin) { "true" } else { "false" }

$BackendProcess = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort") `
    -WorkingDirectory $BackendDir `
    -NoNewWindow `
    -PassThru

$BackendReady = $false
$BackendDeadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $BackendDeadline -and -not $BackendProcess.HasExited) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/ble/dataset-studio/definitions" -TimeoutSec 2
        $BackendReady = $true
        break
    } catch { Start-Sleep -Milliseconds 500 }
    $BackendProcess.Refresh()
}
if (-not $BackendReady) {
    if (-not $BackendProcess.HasExited) { Stop-ProcessTree -ProcessId $BackendProcess.Id }
    throw "El backend arranco sin publicar Dataset Studio. Revise la salida de uvicorn; no se iniciara una interfaz conectada a una API obsoleta."
}

$SdrReady = $false
try {
    $SdrCapabilities = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/ble/capture/devices" -TimeoutSec 30
    $SdrReady = [bool]$SdrCapabilities.available -and @($SdrCapabilities.devices).Count -gt 0
    if ($SdrReady) {
        $SdrLabel = $SdrCapabilities.devices[0].label
        Write-Host "BLE Lab SDR verified: $SdrLabel" -ForegroundColor Green
    } else {
        Write-Host "BLE Lab SDR no disponible: $($SdrCapabilities.reason_code)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "No se pudo verificar el SDR durante el arranque: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Step "Starting frontend on http://localhost:5173"
$env:VITE_APP_SYNC_INTERVAL_MS = "$AppSyncIntervalMs"
$env:VITE_SPECTRUM_POLL_INTERVAL_MS = "$SpectrumPollIntervalMs"
$env:VITE_WATERFALL_POLL_INTERVAL_MS = "$WaterfallPollIntervalMs"
$env:VITE_REMOTE_USER = "$RemoteUser"
$env:VITE_REMOTE_HOST = "$RemoteHost"
$env:VITE_REMOTE_VENV_ACTIVATE = "$RemoteVenvActivate"
$env:VITE_RADIOCONDA_PYTHON = "$RadioCondaPythonPath"
$env:VITE_AI_RESEARCH_PLUGIN_ENABLED = if (Convert-ToBool $EnableAiResearchPlugin) { "true" } else { "false" }
$NpmCommand = Get-CommandPath -Names @("npm.cmd", "npm.exe")
if (-not $NpmCommand) {
    throw "No se encontro npm.cmd. Cierra y abre PowerShell despues de instalar Node.js, y vuelve a ejecutar el script."
}

$FrontendProcess = Start-Process `
    -FilePath $NpmCommand `
    -ArgumentList @("run", "dev", "--", "--host", $FrontendHost, "--strictPort") `
    -WorkingDirectory $FrontendDir `
    -NoNewWindow `
    -PassThru

Write-Host ""
Write-Host "Backend API: http://localhost:$BackendPort"
Write-Host "API docs:    http://localhost:$BackendPort/docs"
Write-Host "Frontend:    http://localhost:5173"
if ($RemoteUser -or $RemoteHost) {
    Write-Host "Remote train target: $RemoteUser@$RemoteHost"
}
Write-Host "App sync interval:       $AppSyncIntervalMs ms"
Write-Host "Spectrum poll interval:  $SpectrumPollIntervalMs ms"
Write-Host "Waterfall poll interval: $WaterfallPollIntervalMs ms"
Write-Host "AI Research Plugin:      $env:AI_RESEARCH_PLUGIN_ENABLED (backend) / $env:VITE_AI_RESEARCH_PLUGIN_ENABLED (frontend)"
Write-Host ""
Write-Host "Pulsa Ctrl+C para parar ambos servicios."

try {
    while (-not $BackendProcess.HasExited -and -not $FrontendProcess.HasExited) {
        Start-Sleep -Seconds 1
        $BackendProcess.Refresh()
        $FrontendProcess.Refresh()
    }
} finally {
    Write-Step "Stopping services"
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-ProcessTree -ProcessId $BackendProcess.Id
    }
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        Stop-ProcessTree -ProcessId $FrontendProcess.Id
    }
}
