import asyncio
import selectors
import sys
from typing import cast
from backend.api.schemas import GenerateTaskSchema
from backend.main import DB_URI_LANGGRAPH
from celery import Celery
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from backend.graph import build_graph, State


from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection


celery_app = Celery("assistente_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")
celery_app.conf.task_routes = {"tasks.run_generate_task": {"queue": "generate_sequential"}}


_loop = None


def get_event_loop():
    global _loop

    if _loop is None or _loop.is_closed():
        if sys.platform == "win32":
            _loop = asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            )
        else:
            _loop = asyncio.new_event_loop()

        asyncio.set_event_loop(_loop)

    return _loop

def run_async_task(coro):
    """Executa corrotinas usando um event loop persistente por worker."""
    loop = get_event_loop()

    try:
        return loop.run_until_complete(coro)
    except Exception:
        raise

async def _run_langgraph_async(thread_id: str, user_input: str):
    async with await AsyncConnection.connect(DB_URI_LANGGRAPH) as conn:
        checkpointer = AsyncPostgresSaver(conn)
        
        builder = build_graph()
        app_graph = builder.compile(checkpointer=checkpointer)
        
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 20,
        }
        inputs = cast(State, {"messages": [HumanMessage(content=user_input)]})
        
        await app_graph.ainvoke(inputs, config=config)

@celery_app.task(bind=True)
def run_langgraph_task(self, thread_id: str, user_input: str):
    run_async_task(_run_langgraph_async(thread_id, user_input))
    return {"status": "concluido", "thread_id": thread_id, "mensagem": "Salvo no DB!"}


async def _run_generate_async(thread_id: str, task: GenerateTaskSchema):
    async with await AsyncConnection.connect(DB_URI_LANGGRAPH) as conn:
        checkpointer = AsyncPostgresSaver(conn)

        builder = build_graph()
        app_graph = builder.compile(checkpointer=checkpointer)

        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 80,
        }

        task_prompt = f"""
            EXECUTE A TAREFA DE IMPLEMENTAÇÃO.

            TÍTULO:
            {task.title}

            DESCRIÇÃO:
            {task.description}

            ARQUIVOS RELEVANTES:
            {task.files}

            MOTIVAÇÃO:
            {task.reason}
        """

        inputs = {
            "messages": [HumanMessage(content=task_prompt)],
            "actual_route": "GENERATE_EXECUTE",
            "active_generate_task": task,
            "thread_id": thread_id,
            "generate_start_idx": 0,
            "workspace_path": task.repo_path,
        }

        await app_graph.ainvoke(inputs, config=config)

@celery_app.task(bind=True)
def run_generate_task(self, thread_id: str, task_data: dict):
    task = GenerateTaskSchema.model_validate(task_data)
    run_async_task(_run_generate_async(thread_id, task))
    
    return {
        "status": "concluido",
        "thread_id": thread_id,
        "task_id": task.id,
    }