@echo off
title Iniciador do Assistente IA
echo ==========================================
echo    LIGANDO A USINA DO ASSISTENTE IA...
echo ==========================================

echo [1/3] Subindo o Redis no Docker...
docker compose up -d
timeout /t 3 /nobreak > nul

echo [2/3] Iniciando o Backend (FastAPI + Frontend)...
start "FastAPI Backend" cmd /k "call .venv\Scripts\activate && uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload"

echo [3/3] Iniciando o Worker (Celery)...
start "Celery Worker" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --concurrency=1 --pool=solo"

echo.
echo Tudo iniciado com sucesso! Acesse http://localhost:8000
echo Pode fechar esta janelinha.
exit