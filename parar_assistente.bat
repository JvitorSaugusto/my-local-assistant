@echo off
curl -s -X POST -H "X-Painel: 1" http://127.0.0.1:8765/api/shutdown >nul 2>&1
echo API e workers encerrados.
timeout /t 2 /nobreak > nul
