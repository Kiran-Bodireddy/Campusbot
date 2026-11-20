. "$PSScriptRoot\_common.ps1"
Start-Transcript -Path "$Root\logs\1_setup.log" -Force | Out-Null
if (-not (Test-Path $Py)) {
    Write-Host "Creating virtual environment .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
& $Py --version
& $Py -m pip install --upgrade pip -q
& $Py -m pip install -q neo4j fastapi "uvicorn[standard]" pydantic pyyaml python-dotenv requests httpx pytest fastmcp pyjwt
& $Py -c "import neo4j, fastapi; print('neo4j driver', neo4j.__version__, '| fastapi', fastapi.__version__)"
Write-Host "SETUP DONE"
Stop-Transcript | Out-Null
