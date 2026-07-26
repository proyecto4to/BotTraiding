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

# --- Secretos locales ---------------------------------------------------------
# Ningun secreto vive en este fichero: esta versionado, asi que cualquier valor
# aqui seria publico, y con el JWT_SECRET se firman tokens de administrador.
# En su lugar se generan una sola vez por maquina y se guardan en .local/
# (gitignored). Para rotarlos: borra .local\dev-secrets.ps1 y vuelve a arrancar.
$secretsFile = Join-Path $localDir 'dev-secrets.ps1'
if (-not (Test-Path $secretsFile)) {
    Write-Host 'Generando secretos locales (primera vez)...' -ForegroundColor Yellow
    $jwt = & $globalPython -c "import secrets; print(secrets.token_urlsafe(48))"
    $pwd = & $globalPython -c "import secrets; print(secrets.token_urlsafe(12))"
    $hash = & $globalPython -c "import bcrypt,sys; print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())" $pwd
    if ($LASTEXITCODE -ne 0 -or -not $hash) {
        throw "No se pudo generar el hash bcrypt. Instala bcrypt: $globalPython -m pip install bcrypt"
    }
    # Se mantiene el usuario BlasJon a proposito: auth-service resincroniza el
    # hash en cada arranque, asi que la contrasena antigua (que estaba
    # versionada, y por tanto es publica) queda sobrescrita. Cambiar de usuario
    # dejaria la cuenta vieja viva con su contrasena conocida.
    @"
# Secretos de desarrollo de esta maquina. NO se versiona (.local/ esta en
# .gitignore). Borra este fichero para regenerarlos.
`$env:JWT_SECRET = '$jwt'
`$env:OPERATOR_USERNAME = 'BlasJon'
`$env:OPERATOR_PASSWORD_HASH = '$hash'
"@ | Set-Content -Path $secretsFile -Encoding UTF8

    $credFile = Join-Path $localDir 'CREDENCIALES.txt'
    @"
Acceso al panel de BotTrading (solo esta maquina)
usuario:    BlasJon
contrasena: $pwd

Generado el $(Get-Date -Format 'yyyy-MM-dd HH:mm'). Sustituye a la contrasena
anterior, que estaba en el repositorio y por tanto ya no era secreta.
Cambiala desde el panel > Seguridad. Si borras .local\dev-secrets.ps1 se
genera una nueva en el siguiente arranque.
"@ | Set-Content -Path $credFile -Encoding UTF8

    Write-Host "  Usuario: BlasJon   Contrasena: $pwd" -ForegroundColor Green
    Write-Host "  (guardada tambien en $credFile)" -ForegroundColor Green
}
. $secretsFile

# --- Entorno comun -----------------------------------------------------------
$env:Path = "C:\Program Files\nodejs;$env:Path"
# El primer usuario que se registre con este email recibe rol admin
# (solo si aun no existe ningun admin).
if (-not $env:AUTH_BOOTSTRAP_ADMIN_EMAIL) { $env:AUTH_BOOTSTRAP_ADMIN_EMAIL = 'proyecto4toano@gmail.com' }
$env:CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'
$env:EXECUTION_MODE = 'paper'
# Datos de mercado sinteticos: el bot funciona directo, sin credenciales de
# broker. Para datos reales: MARKET_DATA_SOURCE=broker + conectar un broker.
if (-not $env:MARKET_DATA_SOURCE) { $env:MARKET_DATA_SOURCE = 'synthetic' }
# Ciclo de autonomia corto en local para ver el bot operar enseguida.
if (-not $env:AUTONOMY_CYCLE_INTERVAL_SECONDS) { $env:AUTONOMY_CYCLE_INTERVAL_SECONDS = '20' }

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
$env:MARKET_DATA_URL        = 'http://127.0.0.1:8014'
$env:AUTONOMY_URL           = 'http://127.0.0.1:8015'

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
    @('trading-engine',       8013),
    @('market-data',          8014),
    @('autonomy-controller',  8015)
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
    # Los servicios internos escuchan SOLO en loopback: varios endpoints de
    # escritura no piden token (colocar orden en broker-connectors, ingesta de
    # portfolio...), asi que exponerlos a la red local seria una via directa
    # para operar saltandose el risk-engine.
    # El gateway es la unica puerta de entrada y si autentica, asi que puede
    # exponerse a proposito (p.ej. para abrir el panel desde el movil):
    #   $env:GATEWAY_BIND = '0.0.0.0'  antes de lanzar este script.
    $bind = if ($name -eq 'gateway' -and $env:GATEWAY_BIND) { $env:GATEWAY_BIND } else { '127.0.0.1' }
    Start-Process -FilePath $python -WorkingDirectory $svcDir `
        -ArgumentList "-m uvicorn app.main:app --host $bind --port $port" `
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
    Write-Host "Los $($services.Count) servicios responden." -ForegroundColor Green
}
Write-Host 'BotTrading: http://localhost:3000  |  API: http://localhost:8000'
