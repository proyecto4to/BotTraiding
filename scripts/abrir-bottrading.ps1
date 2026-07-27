# Abre el panel de BotTrading, arrancando el stack si hiciera falta.
#
# El acceso directo anterior solo lanzaba Chrome en localhost:3000, asi que
# despues de reiniciar el equipo abria una pagina muerta. Esto arranca lo que
# falte (start-bottrading.ps1 ya se salta los servicios vivos), espera a que el
# frontend responda de verdad -- no solo a que el puerto este abierto, porque
# Next.js tarda en compilar la primera vez -- y entonces abre el navegador.
#
# Uso:  powershell -File scripts\abrir-bottrading.ps1

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$panelUrl = 'http://localhost:3000'

function Test-Url([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# Se comprueban LOS DOS a proposito. El frontend puede seguir vivo con todo el
# backend caido (stop-bottrading solia dejarlo asi), y en ese estado el panel
# carga pero no funciona nada: mirar solo :3000 daria "ya esta arriba" y abriria
# una pagina rota.
function Test-PanelReady {
    return (Test-Url $panelUrl) -and (Test-Url 'http://localhost:8000/health')
}

if (Test-PanelReady) {
    Write-Host 'El panel ya esta arriba.'
} else {
    Write-Host 'Arrancando BotTrading...' -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot 'start-bottrading.ps1')

    # Next.js en modo dev compila al primer request, asi que el puerto abre
    # bastante antes de que la pagina sea servible. Se sondea la pagina.
    Write-Host 'Esperando al panel...'
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Test-PanelReady)) {
        if ((Get-Date) -gt $deadline) {
            Write-Warning "El panel no respondio en 3 minutos. Revisa logs\frontend.err.log"
            break
        }
        Start-Sleep -Seconds 3
    }
}

Start-Process $panelUrl

$cred = Join-Path $repoRoot '.local\CREDENCIALES.txt'
if (Test-Path $cred) {
    Write-Host "Usuario y contrasena en: $cred" -ForegroundColor DarkGray
}
