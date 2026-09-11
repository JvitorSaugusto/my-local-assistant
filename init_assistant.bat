@echo off
title Iniciador do Assistente IA
echo ==========================================
echo    LIGANDO A USINA DO ASSISTENTE IA...
echo ==========================================

echo [1/4] Subindo o Redis no Docker...
docker compose up -d
timeout /t 3 /nobreak > nul

echo [2/4] Iniciando o Backend (FastAPI + Frontend)...
start "FastAPI Backend" cmd /k "call .venv\Scripts\activate && uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload"

echo [3/4] Iniciando o Worker Principal (Tarefas Gerais)...
start "Celery Worker Principal" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --queues=celery --pool=threads --concurrency=4 -n principal@localhost"

echo [4/4] Iniciando o Worker do Git (Fila Indiana)...
start "Celery Worker Git" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --queues=generate_sequential --pool=solo -n gitworker@localhost"

echo.
echo Tudo iniciado com sucesso! Acesse http://localhost:8001
echo Pode fechar esta janelinha.
exit