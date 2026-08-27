from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Annotated, cast
from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from backend.agent.graph import State
from fastapi.responses import StreamingResponse


ai_router = APIRouter()

class ChatPayload(BaseModel):
    thread_id: str
    message: str

class BatchPayload(BaseModel):
    thread_id: str
    prompts: list[str]


async def get_compiled_graph(request: Request) -> CompiledStateGraph:
    graph = getattr(request.app.state, "compiled_graph", None)
    if graph is None:
        raise HTTPException(status_code=500, detail="Grafo não inicializado.")
    return graph

CompiledGraphDep = Annotated[CompiledStateGraph, Depends(get_compiled_graph)]

@ai_router.post("/")
async def chat_with_ai(payload: ChatPayload, app_graph: CompiledGraphDep):
    
    config: RunnableConfig = {"configurable": {"thread_id": payload.thread_id}}
    inputs = cast(State, {"messages": [HumanMessage(content=payload.message)]})
    
    async def token_generator():
        async for event in app_graph.astream_events(inputs, config=config, version="v2"):
            
            if event["event"] == "on_chat_model_stream":
                chunk = event["data"].get("chunk")

                if chunk and chunk.content:
                    yield chunk.content
                    
    return StreamingResponse(token_generator(), media_type="text/plain")


@ai_router.get("/{thread_id}/history")
async def get_chat_history(thread_id: str, app_graph: CompiledGraphDep):
    
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    
    state = await app_graph.aget_state(config)
    
    if not state.values or "messages" not in state.values:
        return {"messages": []}
        
    clean_history = [
        {
            "role": "user" if msg.type == "human" else "assistant",
            "content": msg.content,
            "model": getattr(msg, "name", None) 
        }
        for msg in state.values["messages"]
        if msg.type in ["human", "ai"]
    ]
            
    return {"messages": clean_history}


@ai_router.post("/batch/")
async def enviar_tarefas_background(payload: BatchPayload):
    from tasks import run_langgraph_task
    
    for prompt in payload.prompts:
        run_langgraph_task.delay(payload.thread_id, prompt)
        
    return {
        "status": "sucesso", 
        "message": f"{len(payload.prompts)} tarefa(s) enviada(s)."
    }