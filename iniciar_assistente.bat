@echo off
title Iniciador do Assistente IA
cd /d "%~dp0"

echo ==========================================
echo    LIGANDO O ASSISTENTE IA...
echo ==========================================

echo [1/4] Verificando Docker...
docker info >nul 2>&1
if %errorlevel% equ 0 goto docker_ok
echo Docker desligado. Iniciando Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
echo Aguardando o motor do Docker ligar (uns 15 segundos)...
timeout /t 15 /nobreak > nul
goto check_ollama

:docker_ok
echo Docker ja esta rodando!

:check_ollama
echo [2/4] Verificando Ollama...
tasklist | find /i "ollama.exe" > nul
if %errorlevel% equ 0 goto ollama_ok
echo Ollama desligado. Iniciando servidor (escondido)...
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process ollama -ArgumentList 'serve' -WindowStyle Hidden"
timeout /t 3 /nobreak > nul
goto redis

:ollama_ok
echo Ollama ja esta rodando!

:redis
echo [3/4] Subindo Redis/Postgres no Docker...
docker compose up -d
timeout /t 3 /nobreak > nul

:: Se o painel ja esta rodando, so abre as abas (nao duplica API/workers)
curl -s -o nul http://127.0.0.1:8765/api/status
if %errorlevel% equ 0 goto open_tabs

echo [4/4] Limpando tarefas antigas e iniciando o painel (API + workers escondidos)...
.venv\Scripts\python.exe -m celery -A tasks purge -f >nul 2>&1
start "" ".venv\Scripts\pythonw.exe" painel.py

echo Aguardando a API ficar pronta...
set /a tries=0
:wait_api
curl -s -o nul http://127.0.0.1:8001/ && goto open_tabs
set /a tries+=1
if %tries% geq 60 goto open_tabs
timeout /t 1 /nobreak > nul
goto wait_api

:open_tabs
start http://localhost:8001
start http://localhost:8765
echo.
echo Pronto! Logs e botao de reiniciar: http://localhost:8765
timeout /t 3 /nobreak > nul
