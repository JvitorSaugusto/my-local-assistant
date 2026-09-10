from langgraph.graph import START, END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from .config import State
from .nodes import (
    after_enhancer_route,
    context_gatherer_node,
    enhancer_node,
    heavy_analyzer_node,
    note_draft_node,
    note_refine_node,
    return_tool_message,
    router_node,
    standard_node_20b,
    code_node,
    summarize_node,
    route_decision,
    check_context_limit,
)

from .tools import generate_repo_map, list_directory_files, read_file_content



def build_graph():
    builder = StateGraph(State)
    
    all_tools = [list_directory_files, read_file_content, generate_repo_map]
    
    builder.add_node("tools", ToolNode(all_tools))

    builder.add_node("router_node", router_node)
    
    builder.add_node("standard_node_20b", standard_node_20b)
    builder.add_node("code_node", code_node)
    builder.add_node("note_draft_node", note_draft_node)
    builder.add_node("note_refine_node", note_refine_node)
    builder.add_node("context_gatherer_node", context_gatherer_node)
    builder.add_node("heavy_analyzer_node", heavy_analyzer_node)
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
            "note_draft_node": "note_draft_node",
            "context_gatherer_node": "context_gatherer_node",
            "enhancer_node": "enhancer_node",
        }
    )
    
    builder.add_conditional_edges(
        "enhancer_node",
        after_enhancer_route,
        {
            "context_gatherer_node": "context_gatherer_node",
            "router_node": "router_node",
        },
    )
    
    builder.add_conditional_edges(
        "note_draft_node",
        tools_condition,
            {
                "tools": "tools",
                "__end__": "note_refine_node",
            }
        )
    
    builder.add_conditional_edges(
    "code_node",
    tools_condition,
        {
            "tools": "tools",
            "__end__": END,
        }
    )

    builder.add_conditional_edges(
        "context_gatherer_node",
        tools_condition, 
        {
            "tools": "tools", 
            "__end__": "heavy_analyzer_node"
        }
    )
    
    builder.add_conditional_edges(
        "tools", 
        return_tool_message, 
        {
            "code_node": "code_node",
            "note_draft_node": "note_draft_node", 
            "context_gatherer_node": "context_gatherer_node"
        }
    )
    
    builder.add_edge("heavy_analyzer_node", END)

    builder.add_edge("note_refine_node", END)
    builder.add_edge("standard_node_20b", END)
    

    return builder


def compile_graph():
    return build_graph().compile()
    