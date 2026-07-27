# Registra (o quita) el arranque automatico de BotTrading al iniciar sesion.
#
# Por que: el historial que autoriza el paso a dinero real solo se acumula
# mientras el bot corre. Con arranque manual, `min_closed_trades` y el Sharpe
# no avanzan casi nunca -- medido en esta maquina: 13 dias de calendario con
# solo 8 dias de actividad y 0 operaciones cerradas.
#
# Se usa el Programador de tareas y no la carpeta Inicio porque permite
# ejecutar sin ventana visible y reintentar si algo falla al arrancar.
#
# Uso:
#   powershell -File scripts\instalar-arranque-automatico.ps1
#   powershell -File scripts\instalar-arranque-automatico.ps1 -Quitar

param([switch]$Quitar)

$ErrorActionPreference = 'Stop'

$taskName = 'BotTrading'
$startScript = Join-Path $PSScriptRoot 'start-bottrading.ps1'

if ($Quitar) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Arranque automatico quitado. El bot ya no se inicia solo." -ForegroundColor Yellow
    } else {
        Write-Host "No habia ninguna tarea '$taskName' registrada."
    }
    return
}

if (-not (Test-Path $startScript)) { throw "No se encuentra $startScript" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""

# Al iniciar sesion, con un retraso para no competir con el arranque de Windows.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = 'PT1M'

# StartWhenAvailable: si el equipo estaba apagado a la hora prevista, arranca
# en cuanto pueda. Sin limite de duracion: es un servicio, no un job que acaba.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1) `
    -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Arranca los servicios de BotTrading al iniciar sesion.' | Out-Null

Write-Host "Listo: BotTrading arrancara solo al iniciar sesion (1 min de retraso)." -ForegroundColor Green
Write-Host "Para quitarlo:  powershell -File scripts\instalar-arranque-automatico.ps1 -Quitar" -ForegroundColor DarkGray
