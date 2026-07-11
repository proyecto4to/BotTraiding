$ErrorActionPreference = 'Stop'

$repoRoot = 'C:\Users\Dell Vostro\OneDrive\Documentos\GitHub\BotTraiding'
$frontendDir = Join-Path $repoRoot 'frontend'
$gatewayDir = Join-Path $repoRoot 'services/gateway'
$authDir = Join-Path $repoRoot 'services/auth-service'
$logsDir = Join-Path $repoRoot 'logs'
$pythonExe = 'C:\Users\Dell Vostro\AppData\Local\Programs\Python\Python313\python.exe'
$npmExe = 'C:\Program Files\nodejs\npm.cmd'

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

$env:PYTHONPATH = Join-Path $repoRoot 'services'
$env:Path = "C:\Program Files\nodejs;$env:Path"
$env:AUTH_SERVICE_URL = 'http://127.0.0.1:8001'
# Auth firma con este valor por defecto; el gateway NECESITA la variable
# definida para verificar tokens (trading_contracts/auth.py no tiene default).
if (-not $env:JWT_SECRET) { $env:JWT_SECRET = 'dev-insecure-secret-change-me' }
$env:CORS_ORIGINS = 'http://localhost:3000,http://127.0.0.1:3000'

function Test-PortOpen([string]$Server, [int]$Port) {
    try {
        $request = [System.Net.Sockets.TcpClient]::new()
        $request.Connect($Server, $Port)
        $request.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Start-ServiceIfNeeded([string]$Name, [string]$WorkingDir, [string]$LogFile, [string[]]$Args) {
    $portArg = $Args[-1]
    $port = [int]$portArg
    if (Test-PortOpen -Server '127.0.0.1' -Port $port) {
        Write-Host "$Name is already running."
        return
    }

    $stdout = Join-Path $logsDir $LogFile
    $stderr = $stdout -replace '\.log$', '.err.log'
    $commandLine = ($Args | Where-Object { $_ -ne $null }) -join ' '
    Start-Process -FilePath $pythonExe -WorkingDirectory $WorkingDir -ArgumentList $commandLine -RedirectStandardOutput $stdout -RedirectStandardError $stderr -NoNewWindow | Out-Null
    Write-Host "Started $Name."
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 8000)) {
    Start-ServiceIfNeeded -Name 'Gateway' -WorkingDir $gatewayDir -LogFile 'gateway.log' -Args @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8000')
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 8001)) {
    Start-ServiceIfNeeded -Name 'Auth Service' -WorkingDir $authDir -LogFile 'auth-service.log' -Args @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8001')
}

if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Host 'Installing frontend dependencies...'
    & $npmExe install --prefix $frontendDir
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 3000)) {
    Start-Process -FilePath $npmExe -WorkingDirectory $frontendDir -ArgumentList 'run dev' -RedirectStandardOutput (Join-Path $logsDir 'frontend.log') -RedirectStandardError (Join-Path $logsDir 'frontend.err.log') -NoNewWindow | Out-Null
    Write-Host 'Started frontend.'
}
else {
    Write-Host 'Frontend already running.'
}

for ($i = 0; $i -lt 20; $i++) {
    if ((Test-PortOpen -Server '127.0.0.1' -Port 3000) -and (Test-PortOpen -Server '127.0.0.1' -Port 8000) -and (Test-PortOpen -Server '127.0.0.1' -Port 8001)) {
        break
    }
    Start-Sleep -Seconds 1
}

Start-Process 'http://localhost:3000'
Write-Host 'BotTrading is ready at http://localhost:3000'
