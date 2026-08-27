from fastapi import FastAPI
from backend.agent.graph import build_graph
from backend.api.controllers.chat_controller import chat_router
from backend.api.controllers.ai_controller import ai_router
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from contextlib import asynccontextmanager

import os
from dotenv import load_dotenv

load_dotenv()

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
        
        yield
        
app = FastAPI(lifespan=lifespan)

app.include_router(ai_router, prefix="/ai", tags=["InteligenciaArtificial"])
app.include_router(chat_router, prefix="/chats", tags=["ChatInteligenciaArtificial"])