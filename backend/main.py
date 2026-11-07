from fastapi import FastAPI
from backend.graph.builder import build_graph
from backend.api.controllers.chat_controller import chat_router
from backend.api.controllers.ai_controller import ai_router
from backend.api.controllers.tasks_controller import task_router
from backend.api.controllers.upload_controller import upload_router
from backend.rag import rag_startup
from backend.rag.api import rag_router
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from contextlib import asynccontextmanager
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("Variável DATABASE_URL não encontrada!")

DB_URI_LANGGRAPH = DATABASE_URL.replace("+asyncpg", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncConnectionPool(DB_URI_LANGGRAPH, kwargs={"autocommit": True}) as pool:
        checkpointer = AsyncPostgresSaver(pool) # type: ignore
        await checkpointer.setup()
        
        app.state.langgraph_checkpointer = checkpointer
        
        app.state.compiled_graph = build_graph().compile(checkpointer=checkpointer)

        await rag_startup()  # prepara o schema do RAG; nunca derruba o app
        
        yield
        
app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def serve_index():
    index_path = STATIC_DIR / "index.html"

    return FileResponse(index_path)

app.include_router(ai_router, prefix="/api/ai", tags=["InteligenciaArtificial"])
app.include_router(chat_router, prefix="/api/chats", tags=["ChatInteligenciaArtificial"])
app.include_router(task_router, prefix="/api/tasks", tags=["Tarefas"])
app.include_router(upload_router, prefix="/api/uploads", tags=["Uploads"])

app.include_router(rag_router, prefix="/api/rag", tags=["RAG"])
