from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from backend.agent.graph import app_graph, State
from backend.api.schemas import AiRequestSchema


ai_router = APIRouter()

@ai_router.post("/", status_code=200)
async def send_message_for_ia(request: AiRequestSchema):
    config: RunnableConfig ={"configurable": {"thread_id": request.thread_id}}
    
    new_message = HumanMessage(content=request.message)
    updated_state: State = {"messages": [new_message]}
    
    response = app_graph.invoke(updated_state, config=config)
    
    messages = response.get("messages")
    
    if messages and len(messages) > 0:
        last_response = messages[-1].content
    else:
        last_response = "Erro: O assistente não conseguiu gerar uma resposta."
    
    return {"response": last_response}


@ai_router.get("/{thread_id}/history", status_code=200)
async def history_messages(thread_id: str):
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    state = app_graph.get_state(config)
    
    if not state.values or "messages" not in state.values:
        return {"messages": []}
    
    clean_history = []
    
    for msg in state.values["messages"]:
        if msg.type in ["human", "ai"]:
            clean_history.append({
                "role": "user" if msg.type == "human" else "assistant",
                "content": msg.content,
                "model": msg.name if msg.type == "ai" and msg.name else None
            })
    
    return {"messages": clean_history}