. "$PSScriptRoot\_common.ps1"
# Stop any earlier Campusbot server still holding port 8000 (VS Code "Restart Task" can leave the python process running)
$old = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($procId in $old) {
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") {
        Write-Host "Stopping old server process $procId ($($p.ProcessName))"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1
Write-Host "Campus Knowledge Server -> http://localhost:8000  (Ctrl+C to stop)"
& $Py -m uvicorn campus_knowledge_server.server.main:app --host 127.0.0.1 --port 8000 2>&1 | Tee-Object -FilePath "$Root\logs\4_server.log"
