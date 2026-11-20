. "$PSScriptRoot\_common.ps1"
Start-Transcript -Path "$Root\logs\3_check_live.log" -Force | Out-Null
$Out = "$Root\logs\3_check_live.out"
Remove-Item -ErrorAction SilentlyContinue $Out
& $Py -m pytest -q -p no:cacheprovider campus_knowledge_server/tests 2>&1 | ForEach-Object { "$_" } | Tee-Object -FilePath $Out -Append
Write-Host "CHECK DONE"
Stop-Transcript | Out-Null
