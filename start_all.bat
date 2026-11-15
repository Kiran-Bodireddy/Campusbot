@echo off
title SRMIST Campus Knowledge Assistant - Master Launcher
echo ======================================================================
echo          SRMIST CAMPUS KNOWLEDGE ASSISTANT (SYSTEM LAUNCHER)
echo ======================================================================
cd /d "c:\Users\heyit\Downloads\courses"

echo [1/3] Checking Ollama Service...
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Starting Ollama in background...
    start /min "" ollama serve
    timeout /t 3 /nobreak >nul
) else (
    echo  Ollama is active.
)

echo [2/3] Checking FastAPI Server (Port 8000)...
curl -s http://127.0.0.1:8000/health >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Starting FastAPI Tool Server in background...
    start /min "Campus Knowledge Server" cmd /c "uvicorn campus_knowledge_server.server.main:app --host 0.0.0.0 --port 8000"
    timeout /t 3 /nobreak >nul
) else (
    echo  FastAPI Tool Server is active.
)

echo [3/3] Opening Web Assistant in Browser...
start http://localhost:8000/

echo.
echo Launching Interactive Governed Terminal CLI...
echo Type 'mode' in CLI to switch between Instant (20ms) and Generative Qwen 2.5 Mode.
echo.
python cli.py
pause

