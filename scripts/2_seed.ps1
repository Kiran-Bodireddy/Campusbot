. "$PSScriptRoot\_common.ps1"
Start-Transcript -Path "$Root\logs\2_seed.log" -Force | Out-Null
Remove-Item -ErrorAction SilentlyContinue "$Root\logs\2_seed.out"
& $Py seed.py 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath "$Root\logs\2_seed.out" -Append
Write-Host "SEED DONE"
Stop-Transcript | Out-Null
