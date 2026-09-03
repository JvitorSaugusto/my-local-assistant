from langgraph.graph import START, END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from .config import State
from .nodes import (
    after_enhancer_route,
    enhancer_node,
    return_tool_message,
    router_node,
    standard_node_20b,
    code_node,
    note_node,
    heavy_task_node_70b,
    summarize_node,
    route_decision,
    check_context_limit,
)

from .tools import ingest_directory, list_directory_files, read_file_content


def build_graph():
    builder = StateGraph(State)
    
    all_tools = [list_directory_files, read_file_content, ingest_directory]
    
    builder.add_node("tools", ToolNode(all_tools))

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
    
    builder.add_conditional_edges(
        "enhancer_node",
        after_enhancer_route,
        {
            "heavy_task_node_70b": "heavy_task_node_70b",
            "router_node": "router_node",
        },
    )
    
    builder.add_conditional_edges(
        "tools",
        return_tool_message,
        {
            "code_node": "code_node",
            "note_node": "note_node",
            "heavy_task_node_70b": "heavy_task_node_70b",
        }
    )


    builder.add_edge("standard_node_20b", END)
    builder.add_edge("code_node", tools_condition)
    builder.add_edge("note_node", tools_condition)
    builder.add_edge("heavy_task_node_70b", tools_condition)
    builder.add_edge("enhancer_node", "router_node")
    builder.add_edge("tools", "router_node")

    return builder


def compile_graph():
    return build_graph().compile()
    