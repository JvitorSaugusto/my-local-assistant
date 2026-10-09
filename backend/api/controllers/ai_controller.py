import asyncio
import time
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage, RemoveMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from backend.api.history import build_clean_history
from backend.graph.config import State
from backend.graph.node_helpers import now_iso


ai_router = APIRouter()

# execuções em andamento por thread (para poder interromper)
RUNNING: dict[str, asyncio.Task] = {}
STOPPED: set[str] = set()


class ChatPayload(BaseModel):
    thread_id: str
    message: str
    workspace_path: str


class BatchPayload(BaseModel):
    thread_id: str
    prompts: list[str]
    workspace_path: str


class RewindPayload(BaseModel):
    message_id: str


async def get_compiled_graph(request: Request) -> CompiledStateGraph:
    graph = getattr(request.app.state, "compiled_graph", None)
    if graph is None:
        raise HTTPException(status_code=500, detail="Grafo não inicializado.")
    return graph

CompiledGraphDep = Annotated[CompiledStateGraph, Depends(get_compiled_graph)]


def _cancel_running(thread_id: str) -> bool:
    task = RUNNING.get(thread_id)
    if task and not task.done():
        STOPPED.add(thread_id)
        task.cancel()
        return True
    return False


@ai_router.post("/")
async def chat_with_ai(payload: ChatPayload, app_graph: CompiledGraphDep):
    thread_id = payload.thread_id
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    inputs = cast(State, {
        "messages": [
            HumanMessage(
                content=payload.message,
                additional_kwargs={"created_at": now_iso()},
            )
        ],
        "workspace_path": payload.workspace_path,
    })

    started = time.perf_counter()
    task = asyncio.create_task(app_graph.ainvoke(inputs, config=config))
    RUNNING[thread_id] = task

    try:
        result = await task
    except asyncio.CancelledError:
        if thread_id in STOPPED:  # interrupção pedida pelo usuário
            return {"cancelled": True}
        task.cancel()
        raise
    finally:
        STOPPED.discard(thread_id)
        if RUNNING.get(thread_id) is task:
            RUNNING.pop(thread_id, None)

    message = result["messages"][-1]

    return {
        "content": message.content,
        "name": getattr(message, "name", None),
        "created_at": message.additional_kwargs.get("created_at"),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


@ai_router.post("/{thread_id}/stop")
async def stop_generation(thread_id: str):
    return {"stopped": _cancel_running(thread_id)}


@ai_router.post("/{thread_id}/rewind")
async def rewind_chat(thread_id: str, payload: RewindPayload, app_graph: CompiledGraphDep):
    """Apaga a mensagem informada e tudo que veio depois (usado ao editar)."""
    _cancel_running(thread_id)
    await asyncio.sleep(0.1)

    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state = await app_graph.aget_state(config)
    messages = (state.values or {}).get("messages", [])

    idx = next((i for i, m in enumerate(messages) if m.id == payload.message_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    if messages[idx].type != "human":
        raise HTTPException(status_code=400, detail="Só é possível editar mensagens do usuário.")

    update = {
        "messages": [RemoveMessage(id=m.id) for m in messages[idx:] if m.id],
        # evita que estados de uma execução interrompida sequestrem o roteamento
        "active_generate_task": None,
        "generate_start_idx": None,
        "enhanced_prompt": None,
        "heavy_context": None,
        "gatherer_tool_trace": [],
    }
    try:
        await app_graph.aupdate_state(config, update)
    except Exception:
        await app_graph.aupdate_state(config, update, as_node="__start__")

    return {"removed": len(update["messages"])}


@ai_router.get("/{thread_id}/messages")
async def get_chat_history(thread_id: str, app_graph: CompiledGraphDep):
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state = await app_graph.aget_state(config)

    if not state.values or "messages" not in state.values:
        return {"messages": []}

    return {"messages": build_clean_history(state.values["messages"])}


@ai_router.post("/batch/")
async def send_tasks_background(payload: BatchPayload):
    from tasks import run_langgraph_task

    for prompt in payload.prompts:
        run_langgraph_task.delay(payload.thread_id, prompt, payload.workspace_path,)

    return {
        "status": "sucesso",
        "message": f"{len(payload.prompts)} tarefa(s) enviada(s)."
    }
