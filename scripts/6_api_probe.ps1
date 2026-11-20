. "$PSScriptRoot\_common.ps1"
& $Py scripts\api_security_probe.py 2>&1 | Tee-Object -FilePath "$Root\logs\6_api_probe.out"
