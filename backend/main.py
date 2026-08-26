from fastapi import FastAPI
from backend.api.controllers.chat_controller import chat_router
from backend.api.controllers.ai_controller import ai_router

app = FastAPI()

app.include_router(ai_router, prefix="/ai", tags=["InteligenciaArtificial"])
app.include_router(chat_router, prefix="/chats", tags=["ChatInteligenciaArtificial"])