# Arranque local completo de BotTrading (sin Docker).
# Levanta los 14 servicios Python (cada uno con su .venv) + frontend Next.js.
# Datos: SQLite por servicio en .local/ (en Docker se usa Postgres+Alembic).
# Uso:  powershell -File scripts\start-bottrading.ps1
# Para reiniciar todo:  scripts\stop-bottrading.ps1  y luego este script.

$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Users\Dell Vostro\OneDrive\Documentos\GitHub\BotTraiding'
$logsDir = Join-Path $repoRoot 'logs'
$localDir = Join-Path $repoRoot '.local'
$globalPython = 'C:\Users\Dell Vostro\AppData\Local\Programs\Python\Python313\python.exe'
$npmExe = 'C:\Program Files\nodejs\npm.cmd'

foreach ($d in @($logsDir, $localDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# --- Entorno comun -----------------------------------------------------------
$env:Path = "C:\Program Files\nodejs;$env:Path"
# Auth firma con este valor por defecto; el gateway y demas servicios NECESITAN
# la variable definida para verificar tokens.
if (-not $env:JWT_SECRET) { $env:JWT_SECRET = 'dev-insecure-secret-change-me' }
$env:CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:EXECUTION_MODE = 'paper'

# URLs entre servicios (mismo mapa de puertos que docker-compose)
$env:AUTH_SERVICE_URL       = 'http://127.0.0.1:8001'
$env:STRATEGY_ENGINE_URL    = 'http://127.0.0.1:8002'
$env:RISK_ENGINE_URL        = 'http://127.0.0.1:8003'
$env:PORTFOLIO_ENGINE_URL   = 'http://127.0.0.1:8004'
$env:AI_ENGINE_URL          = 'http://127.0.0.1:8005'
$env:EXECUTION_ENGINE_URL   = 'http://127.0.0.1:8006'
$env:BROKER_CONNECTORS_URL  = 'http://127.0.0.1:8007'
$env:BACKTESTER_URL         = 'http://127.0.0.1:8008'
$env:OPTIMIZER_URL          = 'http://127.0.0.1:8009'
$env:PAPER_TRADING_URL      = 'http://127.0.0.1:8010'
$env:NOTIFICATION_SERVICE_URL = 'http://127.0.0.1:8011'
$env:TRADING_ENGINE_URL     = 'http://127.0.0.1:8013'

# name, port
$services = @(
    @('gateway',              8000),
    @('auth-service',         8001),
    @('strategy-engine',      8002),
    @('risk-engine',          8003),
    @('portfolio-engine',     8004),
    @('ai-engine',            8005),
    @('execution-engine',     8006),
    @('broker-connectors',    8007),
    @('backtester',           8008),
    @('optimizer',            8009),
    @('paper-trading',        8010),
    @('notification-service', 8011),
    @('scheduler',            8012),
    @('trading-engine',       8013)
)

function Test-PortOpen([int]$Port) {
    try {
        $c = [System.Net.Sockets.TcpClient]::new()
        $c.Connect('127.0.0.1', $Port); $c.Close(); return $true
    } catch { return $false }
}

foreach ($svc in $services) {
    $name = $svc[0]; $port = $svc[1]
    if (Test-PortOpen -Port $port) { Write-Host "$name ya corre en :$port"; continue }

    $svcDir = Join-Path $repoRoot "services\$name"
    $venvPython = Join-Path $svcDir '.venv\Scripts\python.exe'
    $python = if (Test-Path $venvPython) { $venvPython } else { $globalPython }

    # SQLite propio por servicio (solo desarrollo local; Docker usa Postgres)
    if (Test-Path (Join-Path $svcDir 'app\models.py')) {
        $dbFile = (Join-Path $localDir "$name.db") -replace '\\', '/'
        $env:DATABASE_URL = "sqlite:///$dbFile"
        # Crear tablas si faltan (las migraciones Alembic usan tipos Postgres,
        # asi que localmente se usa create_all sobre los modelos).
        & $python -c "import sys; sys.path.insert(0, r'$svcDir'); from app.db import engine; import app.models as m; m.Base.metadata.create_all(bind=engine)" 2>$null
        if ($LASTEXITCODE -ne 0) { Write-Warning "$name : fallo create_all (endpoints de DB pueden dar 500)" }
    } else {
        Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    }

    $out = Join-Path $logsDir "$name.log"
    $errLog = Join-Path $logsDir "$name.err.log"
    Start-Process -FilePath $python -WorkingDirectory $svcDir `
        -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port $port" `
        -RedirectStandardOutput $out -RedirectStandardError $errLog -NoNewWindow | Out-Null
    Write-Host "Iniciado $name en :$port"
}
Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue

# --- Frontend ----------------------------------------------------------------
$frontendDir = Join-Path $repoRoot 'frontend'
if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Host 'Instalando dependencias del frontend...'
    & $npmExe install --prefix $frontendDir
}
if (-not (Test-PortOpen -Port 3000)) {
    Start-Process -FilePath $npmExe -WorkingDirectory $frontendDir -ArgumentList 'run dev' `
        -RedirectStandardOutput (Join-Path $logsDir 'frontend.log') `
        -RedirectStandardError (Join-Path $logsDir 'frontend.err.log') -NoNewWindow | Out-Null
    Write-Host 'Frontend iniciado.'
} else { Write-Host 'Frontend ya corre en :3000' }

# --- Espera y verificacion ----------------------------------------------------
Write-Host "`nEsperando servicios..."
Start-Sleep -Seconds 8
$down = @()
foreach ($svc in $services) {
    if (-not (Test-PortOpen -Port $svc[1])) { $down += "$($svc[0]) (:$($svc[1]))" }
}
if ($down.Count -gt 0) {
    Write-Warning ("Sin responder: " + ($down -join ', ') + " - revisa logs\<servicio>.err.log")
} else {
    Write-Host 'Los 14 servicios responden.' -ForegroundColor Green
}
Write-Host 'BotTrading: http://localhost:3000  |  API: http://localhost:8000'
