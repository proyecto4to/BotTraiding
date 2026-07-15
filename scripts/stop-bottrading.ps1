# Detiene todos los servicios Python locales de BotTrading (puertos 8000-8013).
# No toca el frontend (:3000); cerralo con Ctrl+C o matando el proceso node.

$ports = 8000..8015
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq 'python') {
            Stop-Process -Id $proc.Id -Force -Confirm:$false
            Write-Host "Detenido python :$port (PID $($proc.Id))"
        }
    }
}
Write-Host 'Listo.'
