@echo off
title Iniciador do Assistente IA

:: Forca o script a rodar na pasta correta (corrige bugs de Modo Administrador)
cd /d "%~dp0"

echo ==========================================
echo    LIGANDO A USINA DO ASSISTENTE IA...
echo ==========================================

echo [1/7] Verificando Docker...
docker info >nul 2>&1
if %errorlevel% equ 0 goto docker_ok
echo Docker desligado. Iniciando Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
echo Aguardando o motor do Docker ligar (isso pode levar uns 15 segundos)...
timeout /t 15 /nobreak > nul
goto check_ollama

:docker_ok
echo Docker ja esta rodando!

:check_ollama
echo [2/7] Verificando Ollama...
tasklist | find /i "ollama.exe" > nul
if %errorlevel% equ 0 goto ollama_ok
echo Ollama desligado. Iniciando servidor...
start "Ollama" cmd /c "ollama serve"
timeout /t 3 /nobreak > nul
goto next_steps

:ollama_ok
echo Ollama ja esta rodando!

:next_steps
echo [3/7] Subindo o Redis no Docker...
docker compose up -d
timeout /t 3 /nobreak > nul

echo [4/7] Limpando tarefas antigas (Fantasmas do Celery)...
call .venv\Scripts\activate && celery -A tasks purge -f

echo [5/7] Iniciando o Backend (FastAPI + Frontend)...
start "FastAPI Backend" cmd /k "call .venv\Scripts\activate && uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload"

echo [6/7] Iniciando o Worker Principal (Tarefas Gerais)...
start "Celery Worker Principal" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --queues=celery --pool=threads --concurrency=4 -n principal@localhost"

echo [7/7] Iniciando o Worker do Git (Fila Indiana)...
start "Celery Worker Git" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --queues=generate_sequential --pool=solo -n gitworker@localhost"

echo.
echo Tudo iniciado com sucesso! Abrindo o navegador...
timeout /t 3 /nobreak > nul
start http://localhost:8001

echo.
echo Pressione qualquer tecla para fechar esta janela...
pause > nul