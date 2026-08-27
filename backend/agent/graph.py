from typing import Annotated, TypedDict,NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage, RemoveMessage

from backend.agent.agent import load_llm
from backend.agent.prompts import CODE_NODE_PROMPT, HEAVY_NODE_PROMPT, NOTE_NODE_PROMPT, ROUTER_NODE_PROMPT, STANDARD_NODE_PROMPT



class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    actual_route: str
    heavy_task_id: NotRequired[int | None]
    router_decision: NotRequired[str | None]
    summary: str
    

router_llm = load_llm().with_config(config={"configurable": {"model": "qwen3:0.6b", "temperature": 0.0, "max_tokens": 10}})
standard_llm = load_llm().with_config(config={"configurable": {"model": "gpt-oss:20b", "temperature": 0.2}})
code_llm = load_llm().with_config(config={"configurable": {"model": "qwen3-coder:30b", "temperature": 0.2}})
note_llm = load_llm().with_config(config={"configurable": {"model": "qwen3:30b-a3b", "temperature": 0.2}})
heavy_llm = load_llm().with_config(config={"configurable": {"model": "DeepSeek-R1:70b", "temperature": 0.2}})

def router_node(state: State):
    last_msg = state["messages"][-1].content
    
    if "@heavy" in last_msg.lower():
        last_msg_limpa = last_msg.lower().replace("@heavy", "").strip()
        state["messages"][-1].content = last_msg_limpa
        
        return {"actual_route": "HEAVY"}

    router_prompt = SystemMessage(content=ROUTER_NODE_PROMPT)
    
    decision = router_llm.invoke([router_prompt, HumanMessage(content=last_msg)])
    
    category = decision.content.strip().upper()
    
    if category not in ["NORMAL", "CODE", "HEAVY", "NOTES"]:
        category = "NORMAL"
        
    return {"actual_route": category}


def standard_node_20b(state: State):
    persona = SystemMessage(content=STANDARD_NODE_PROMPT)
    response = standard_llm.invoke([persona] + state["messages"])
    response.name = "GPT-OSS (20B)"
    return {"messages": [response]}

def code_node(state: State):
    persona = SystemMessage(content=CODE_NODE_PROMPT)
    
    response = code_llm.invoke([persona] + state["messages"])
    response.name = "Qwen3 Coder (30B)"
    return {
        "messages": [response],
    }
    
def note_node(state: State):
    persona = SystemMessage(content=NOTE_NODE_PROMPT)
    
    response = note_llm.invoke([persona] + state["messages"])
    response.name = "Qwen3 Notas (30B)"
    return {
        "messages": [response],
    }

def heavy_task_node_70b(state: State):
    persona = SystemMessage(content=HEAVY_NODE_PROMPT)
    
    response = heavy_llm.invoke([persona] + state["messages"])
    response.name = "DeepSeek R1 (70B)"
    return {
        "messages": [response],
    }

def route_decision(state: State):
    destiny = state.get("actual_route", "NORMAL")
    
    if destiny == "CODE":
        return "code_response"
    elif destiny == "HEAVY":
        return "heavy_task_response"
    elif destiny == "NOTES":
        return "note_response"
    else:
        return "standard_response"

def check_context_limit(state: State):
    messages_qnt = len(state["messages"])
    
    if messages_qnt > 10:
        return "go_to_summarize"
    return "go_to_router"

def summarize_node(state: State):
    actual_summary = state.get("summary", "")
    old_messages = state["messages"]
    
    if actual_summary:
        prompt = f"Resumo atual: {actual_summary}\n\nAtualize este resumo incorporando as mensagens recentes. Mantenha em apenas um parágrafo."
    else:
        prompt = "Resuma todo este histórico de conversa acima em apenas um parágrafo."
        
    order = HumanMessage(content=prompt)
    
    response = standard_llm.invoke(old_messages + [order])
    
    return {"summary": response.content}
    


def build_graph():
    builder = StateGraph(State)

    builder.add_node("router_node", router_node)
    
    builder.add_node("standard_node_20b", standard_node_20b)
    builder.add_node("code_node", code_node)
    builder.add_node("note_node", note_node)
    builder.add_node("heavy_task_node_70b", heavy_task_node_70b)
    builder.add_node("summarize_node", summarize_node)
    
    
    builder.add_conditional_edges(
        START,
            check_context_limit,
            {
                "go_to_summarize":"summarize_node",
                "go_to_router":"router_node"
            }
        )    

    builder.add_edge("summarize_node", "router_node")

    builder.add_conditional_edges(
        "router_node",
        route_decision,
        {
            "standard_response": "standard_node_20b",
            "code_response": "code_node",
            "note_response": "note_node",
            "heavy_task_response": "heavy_task_node_70b",
        }
    )


    builder.add_edge("standard_node_20b", END)
    builder.add_edge("code_node", END)
    builder.add_edge("note_node", END)
    builder.add_edge("heavy_task_node_70b", END)

    return builder


def compile_graph():
    return build_graph().compile()
    