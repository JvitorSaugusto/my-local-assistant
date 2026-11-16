import asyncio
import time
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage, RemoveMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from backend.api.chat_rotation import chat_size, maybe_rotate_chat, release_active_tasks
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


class NewChatPayload(BaseModel):
    workspace_path: str = ""


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


def _is_busy(thread_id: str) -> bool:
    task = RUNNING.get(thread_id)
    return bool(task and not task.done())


@ai_router.post("/")
async def chat_with_ai(payload: ChatPayload, app_graph: CompiledGraphDep):
    thread_id = payload.thread_id
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # Chat cheio: continua em um chat novo (com resumo), mas só quando nenhuma task/execução do chat está ativa.
    rotation = await maybe_rotate_chat(app_graph, thread_id, payload.workspace_path, busy=_is_busy(thread_id))
    if rotation["status"] in ("rotated", "already"):
        return {**rotation["response"], "carry_message": payload.message}

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
        "chat_full": rotation["status"] == "waiting",
    }


@ai_router.post("/{thread_id}/stop")
async def stop_generation(thread_id: str):
    return {"stopped": _cancel_running(thread_id)}


@ai_router.post("/{thread_id}/new-chat")
async def continue_in_new_chat(thread_id: str, payload: NewChatPayload, app_graph: CompiledGraphDep):
    """Continua esta conversa em um chat novo (com resumo), mesmo que ainda não tenha atingido o limite."""
    rotation = await maybe_rotate_chat(
        app_graph, thread_id, payload.workspace_path, busy=_is_busy(thread_id), force=True
    )
    status = rotation["status"]
    if status in ("rotated", "already"):
        return rotation["response"]
    if status == "waiting":
        raise HTTPException(
            status_code=409,
            detail="Há tasks ou uma execução em andamento neste chat. Aguarde terminarem para continuar em um chat novo.",
        )
    if status == "not_needed":
        raise HTTPException(status_code=400, detail="Este chat ainda não tem conversa para continuar em um chat novo.")
    raise HTTPException(status_code=500, detail=rotation.get("detail") or "Não foi possível criar o chat novo.")


@ai_router.get("/{thread_id}/size")
async def get_chat_size(thread_id: str, app_graph: CompiledGraphDep):
    """Tamanho estimado do chat, se está cheio, tasks ativas e, se já foi trocado, para qual chat."""
    try:
        return await chat_size(app_graph, thread_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível medir o chat: {exc}")


@ai_router.post("/{thread_id}/release-tasks")
async def release_stuck_tasks(thread_id: str):
    """Libera tasks presas em queued/running (worker caiu) para o chat poder continuar em um chat novo."""
    if _is_busy(thread_id):
        raise HTTPException(status_code=409, detail="Há uma execução ativa neste chat. Use Parar antes de liberar as tasks.")
    return {"released": await release_active_tasks(thread_id)}


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
