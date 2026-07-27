# Detiene BotTrading: los 16 servicios Python (8000-8015) y el frontend (:3000).
#
# El frontend se para tambien a proposito. Dejarlo vivo con el backend caido
# deja el panel en el peor estado posible: la pagina carga, parece que todo va
# bien, y cada accion falla. "Parado" tiene que significar parado.

$stopped = 0

foreach ($port in 8000..8015) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq 'python') {
            Stop-Process -Id $proc.Id -Force -Confirm:$false
            Write-Host "Detenido python :$port (PID $($proc.Id))"
            $stopped++
        }
    }
}

# El dev server de Next.js arranca procesos node hijos; se para el que tiene el
# puerto y sus descendientes, o el arbol queda huerfano ocupando :3000.
$feConns = Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue
foreach ($conn in $feConns) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -match 'node|npm') {
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $($proc.Id)" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false -ErrorAction SilentlyContinue }
        Stop-Process -Id $proc.Id -Force -Confirm:$false
        Write-Host "Detenido frontend :3000 (PID $($proc.Id))"
        $stopped++
    }
}

if ($stopped -eq 0) { Write-Host 'No habia nada corriendo.' } else { Write-Host 'Listo.' }
