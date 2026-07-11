$repoRoot = 'C:\Users\Dell Vostro\OneDrive\Documentos\GitHub\BotTraiding'
$frontendDir = Join-Path $repoRoot 'frontend'
$gatewayDir = Join-Path $repoRoot 'services/gateway'
$authDir = Join-Path $repoRoot 'services/auth-service'
$pythonExe = 'C:\Users\Dell Vostro\AppData\Local\Programs\Python\Python313\python.exe'
$npmExe = 'C:\Program Files\nodejs\npm.cmd'

$env:PYTHONPATH = Join-Path $repoRoot 'services'
$env:Path = "C:\Program Files\nodejs;$env:Path"
$env:AUTH_SERVICE_URL = 'http://127.0.0.1:8001'

function Test-PortOpen([string]$Server, [int]$Port) {
    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $client.Connect($Server, $Port)
        $client.Close()
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 8000)) {
    Start-Process -FilePath $pythonExe -WorkingDirectory $gatewayDir -ArgumentList '-m uvicorn app.main:app --host 0.0.0.0 --port 8000' -WindowStyle Hidden
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 8001)) {
    Start-Process -FilePath $pythonExe -WorkingDirectory $authDir -ArgumentList '-m uvicorn app.main:app --host 0.0.0.0 --port 8001' -WindowStyle Hidden
}

if (-not (Test-PortOpen -Server '127.0.0.1' -Port 3000)) {
    Start-Process -FilePath $npmExe -WorkingDirectory $frontendDir -ArgumentList 'run dev' -WindowStyle Hidden
}

Start-Sleep -Seconds 4
Start-Process 'http://localhost:3000'
