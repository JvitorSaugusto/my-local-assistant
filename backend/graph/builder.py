from langgraph.graph import START, END, StateGraph
from .config import State
from .nodes import (
    enhancer_node,
    router_node,
    standard_node_20b,
    code_node,
    note_node,
    heavy_task_node_70b,
    summarize_node,
    route_decision,
    check_context_limit,
)


def build_graph():
    builder = StateGraph(State)

    builder.add_node("router_node", router_node)
    
    builder.add_node("standard_node_20b", standard_node_20b)
    builder.add_node("code_node", code_node)
    builder.add_node("note_node", note_node)
    builder.add_node("heavy_task_node_70b", heavy_task_node_70b)
    builder.add_node("summarize_node", summarize_node)
    builder.add_node("enhancer_node", enhancer_node)
    
    
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
            "standard_node_20b": "standard_node_20b",
            "code_node": "code_node",
            "note_node": "note_node",
            "heavy_task_node_70b": "heavy_task_node_70b",
            "enhancer_node": "enhancer_node",
        }
    )


    builder.add_edge("standard_node_20b", END)
    builder.add_edge("code_node", END)
    builder.add_edge("note_node", END)
    builder.add_edge("heavy_task_node_70b", END)
    builder.add_edge("enhancer_node", "router_node")

    return builder


def compile_graph():
    return build_graph().compile()
    