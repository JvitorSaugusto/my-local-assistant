@echo off
title Iniciador do Assistente IA
echo ==========================================
echo    LIGANDO A USINA DO ASSISTENTE IA...
echo ==========================================

echo [1/4] Subindo o Redis no Docker...
docker compose up -d
:: Espera 3 segundos pro Redis respirar antes de ligar o resto
timeout /t 3 /nobreak > nul

echo [2/4] Iniciando o Backend (FastAPI)...
:: O comando 'start' abre uma nova janela preta. 
:: O 'cmd /k' mantém ela aberta. O 'call' ativa o venv.
start "FastAPI Backend" cmd /k "call .venv\Scripts\activate && uvicorn backend.main:app --reload"

echo [3/4] Iniciando o Worker (Celery)...
start "Celery Worker" cmd /k "call .venv\Scripts\activate && celery -A tasks worker --loglevel=info --concurrency=1 --pool=solo"

echo [4/4] Iniciando o Frontend (Streamlit)...
start "Streamlit Frontend" cmd /k "call .venv\Scripts\activate && streamlit run frontend/frontend.py"

echo.
echo Tudo iniciado com sucesso! Pode fechar esta janelinha.
exit