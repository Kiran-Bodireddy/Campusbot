$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force -Path "$Root\logs" | Out-Null
$Py = "$Root\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
