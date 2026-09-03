
from langchain_ollama import ChatOllama
from langgraph.graph import add_messages
from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain.chat_models import init_chat_model
from typing import Annotated, Literal, NotRequired, TypedDict, cast
from pydantic import Field
from backend.graph.tools import ingest_directory, list_directory_files, read_file_content

    
class RouteDecision(BaseModel):
    route: Literal["NORMAL", "CODE", "NOTES"] = Field(
        description="Categoria da intenção principal da mensagem do usuário"
    )
    
    
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    actual_route: str
    heavy_task_id: NotRequired[int | None]
    router_decision: NotRequired[str | None]
    summary: str
    enhance_before_heavy: bool
    active_node: str
    enhanced_prompt: str | None
    
def load_llm() -> BaseChatModel:
    model = cast(
        "BaseChatModel",
        init_chat_model(
            model="gpt-oss:20b",
            model_provider="ollama",
            temperature=0.2,
            configurable_fields=("model", "model_provider", "temperature", "max_tokens"),
        ),
    )

    assert hasattr(model, "bind_tools")
    assert hasattr(model, "invoke")
    assert hasattr(model, "with_config")

    return model


FILE_TOOLS_SURGICAL = [list_directory_files, read_file_content]
FILE_TOOLS_FULL = [list_directory_files, read_file_content, ingest_directory]


router_structured = load_llm().with_structured_output(RouteDecision).with_config(config={"configurable": { "model": "qwen3:4b", "temperature": 0.0, "max_tokens": 32,}})
standard_llm = ChatOllama(model="gpt-oss:20b", temperature=0.2, num_predict=4096, num_ctx=16384,)
code_llm = ChatOllama(model="gpt-oss:20b", temperature=0.1, num_predict=4096, num_ctx=16384,)
note_llm_draft = ChatOllama(model="qwen3:30b-a3b", temperature=0.2, num_predict=8192, num_ctx=32768, think=True,)
note_llm_final = ChatOllama(model="qwen3:30b-a3b", temperature=0.2, num_predict=24576, num_ctx=32768, think=True,)
heavy_llm = ChatOllama(model="DeepSeek-R1:70b", temperature=0.1, num_predict=16384, num_ctx=32768)

code_llm_with_tools = code_llm.bind_tools(FILE_TOOLS_SURGICAL)
note_llm_draft_with_tools = note_llm_draft.bind_tools(FILE_TOOLS_SURGICAL)
heavy_llm_with_tools = heavy_llm.bind_tools(FILE_TOOLS_FULL)