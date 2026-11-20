. "$PSScriptRoot\_common.ps1"
Write-Host "Running the 200-question benchmark (server must be running on http://127.0.0.1:8000 for the HTTP security items)..."
& $Py campus_knowledge_server\eval\eval_suite_200.py 2>&1 | Tee-Object -FilePath "$Root\logs\5_benchmark.out"
Write-Host "BENCHMARK DONE - report: campus_knowledge_server\eval\eval_suite_200_report.json"
