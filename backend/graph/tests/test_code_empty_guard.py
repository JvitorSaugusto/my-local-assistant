from types import SimpleNamespace
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.graph import nodes


def test_code_node_recovers_from_empty_response(monkeypatch):
    class FakeLLMWithTools:
        def invoke(self, context):
            return AIMessage(content="", tool_calls=[])

    class FakeLLMPlain:
        def invoke(self, context):
            return AIMessage(content="Endpoint encontrado em portal_internal.py.")

    monkeypatch.setattr(nodes, "code_llm_with_tools", FakeLLMWithTools())
    monkeypatch.setattr(nodes, "code_llm", FakeLLMPlain())

    state = {
        "messages": [
            HumanMessage(content="localize o endpoint users/sync"),
            ToolMessage(content="portal_internal.py:10: @router.post('/api/internal/portal/users/sync')", tool_call_id="1", name="search_in_file"),
        ],
        "workspace_path": "",
        "summary": "",
        "preset": "default",
    }
    out = nodes.code_node(state)
    msg = out["messages"][-1]
    assert "portal_internal.py" in msg.content


def test_code_node_falls_back_to_tool_summary_if_retry_also_empty(monkeypatch):
    class EmptyLLM:
        def invoke(self, context):
            return AIMessage(content="", tool_calls=[])

    monkeypatch.setattr(nodes, "code_llm_with_tools", EmptyLLM())
    monkeypatch.setattr(nodes, "code_llm", EmptyLLM())

    state = {
        "messages": [
            HumanMessage(content="localize auth/jwt"),
            ToolMessage(content="auth.py:12: '/api/auth/jwt/'", tool_call_id="1", name="search_in_file"),
        ],
        "workspace_path": "",
        "summary": "",
        "preset": "default",
    }
    out = nodes.code_node(state)
    msg = out["messages"][-1]
    assert msg.content.strip() != ""
    assert "/api/auth/jwt/" in msg.content
