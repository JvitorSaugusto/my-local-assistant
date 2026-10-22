import asyncio
import selectors
import sys
from typing import cast
from backend.api.schemas import GenerateTaskSchema
from backend.main import DB_URI_LANGGRAPH
from backend.database.config import async_session_env
from backend.database.models import TaskModel
from backend.graph.tools import reset_branch_call_counter
from celery import Celery
from celery.signals import worker_ready
from sqlalchemy import update
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from backend.graph import build_graph, State


from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection


celery_app = Celery("assistente_tasks", broker="redis://localhost:6379/0", backend="redis://localhost:6379/0")
celery_app.conf.task_routes = {"tasks.run_generate_task": {"queue": "generate_sequential"}}
# Fila sequencial: não deixa o worker reservar tarefas que ainda não vai executar.
celery_app.conf.worker_prefetch_multiplier = 1


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

async def _run_langgraph_async(thread_id: str, user_input: str, workspace_path: str | None = None):
    async with await AsyncConnection.connect(DB_URI_LANGGRAPH) as conn:
        checkpointer = AsyncPostgresSaver(conn)
        
        builder = build_graph()
        app_graph = builder.compile(checkpointer=checkpointer)
        
        config: RunnableConfig = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 20,
        }
        state_input: dict = {"messages": [HumanMessage(content=user_input)]}
        if workspace_path:
            state_input["workspace_path"] = workspace_path
        inputs = cast(State, state_input)
        
        await app_graph.ainvoke(inputs, config=config)

@celery_app.task(bind=True)
def run_langgraph_task(self, thread_id: str, user_input: str, workspace_path: str | None = None):
    run_async_task(_run_langgraph_async(thread_id, user_input, workspace_path))
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
            "messages": [HumanMessage(content=task_prompt, name="hidden_task_prompt", additional_kwargs={'message_tag': 'internal_task_instruction'})],
            "actual_route": "GENERATE_EXECUTE",
            "active_generate_task": task,
            "thread_id": thread_id,
            "generate_start_idx": 0,
            "workspace_path": task.repo_path,
        }

        await app_graph.ainvoke(inputs, config=config)

async def _claim_task(task_id: int) -> bool:
    """queued -> running, de forma atômica. False se a tarefa já não está 'queued'
    (ex.: mensagem duplicada ou tarefa já finalizada): nesse caso não executa de novo."""
    async with async_session_env() as db:
        result = await db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.status == "queued")
            .values(status="running")
        )
        await db.commit()
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]


async def _fail_task(task_id: int, error: str) -> None:
    """Marca como 'failed' SÓ se ainda estiver queued/running: nunca sobrescreve
    um 'completed' ou um 'failed' (com sua mensagem de erro) já gravado pelo grafo."""
    async with async_session_env() as db:
        await db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id, TaskModel.status.in_(("queued", "running")))
            .values(status="failed", last_error=error[:4000])
        )
        await db.commit()


async def _fail_orphaned_running_tasks() -> None:
    async with async_session_env() as db:
        await db.execute(
            update(TaskModel)
            .where(TaskModel.status == "running")
            .values(
                status="failed",
                last_error="O worker foi reiniciado durante a execução. Use 'Reiniciar' para tentar de novo.",
            )
        )
        await db.commit()


@worker_ready.connect
def _recover_orphaned_tasks(sender=None, **kwargs):
    """Ao subir, tarefas ainda 'running' são de um worker que caiu. As 'queued' continuam
    válidas (a mensagem segue no broker). Premissa: um único worker na fila sequencial."""
    try:
        run_async_task(_fail_orphaned_running_tasks())
    except Exception as exc:  # não impede o worker de subir
        print(f"[CELERY] Não foi possível recuperar tarefas órfãs: {exc}")


async def _execute_generate(thread_id: str, task: GenerateTaskSchema) -> bool:
    if task.id is not None and not await _claim_task(task.id):
        print(f"[CELERY] Tarefa {task.id} não está 'queued'; execução ignorada.")
        return False

    reset_branch_call_counter(task.repo_path)

    await _run_generate_async(thread_id, task)

    if task.id is not None:
        # O grafo grava completed/failed ao terminar. Se acabou sem isso, não deixa 'running'.
        await _fail_task(
            task.id, "A execução terminou sem registrar um resultado final para a tarefa."
        )
    return True


@celery_app.task(bind=True)
def run_generate_task(self, thread_id: str, task_data: dict):
    task_id = task_data.get("id") if isinstance(task_data, dict) else None

    try:
        task = GenerateTaskSchema.model_validate(task_data)
        executed = run_async_task(_execute_generate(thread_id, task))
    except BaseException as exc:
        if task_id is not None:
            try:
                run_async_task(_fail_task(task_id, f"{type(exc).__name__}: {exc}"))
            except Exception as db_exc:  # nunca esconde o erro original
                print(f"[CELERY] Falha ao marcar a tarefa {task_id} como failed: {db_exc}")
        raise

    return {
        "status": "concluido" if executed else "ignorado",
        "thread_id": thread_id,
        "task_id": task.id,
    }
