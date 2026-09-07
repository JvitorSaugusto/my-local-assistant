
from langchain_ollama import ChatOllama
from langgraph.graph import add_messages
from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain.chat_models import init_chat_model
from typing import Annotated, Literal, NotRequired, TypedDict, cast
from pydantic import Field
from backend.graph.tools import generate_repo_map, ingest_directory, list_directory_files, read_file_content

    
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

FILE_TOOLS_SURGICAL = [list_directory_files, read_file_content]
FILE_TOOLS_FULL = [list_directory_files, read_file_content, generate_repo_map]


router_structured = ChatOllama(model="qwen3:4b", temperature=0.0, num_predict=200, num_ctx=8192,).with_structured_output(RouteDecision)

standard_llm = ChatOllama(model="gpt-oss:20b", temperature=0.2, num_predict=4096, num_ctx=131072)
code_llm = ChatOllama(model="gpt-oss:20b", temperature=0.1, num_predict=4096, num_ctx=131072)

note_llm_draft = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=8192, num_ctx=65536, think=True)
note_llm_final = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=24576, num_ctx=65536, think=True)

heavy_llm = ChatOllama(model="deepseek-r1:32b", temperature=0.6, num_predict=16384, num_ctx=65536)

code_llm_with_tools = code_llm.bind_tools(FILE_TOOLS_SURGICAL)
note_llm_draft_with_tools = note_llm_draft.bind_tools(FILE_TOOLS_SURGICAL)
heavy_llm_with_tools = heavy_llm.bind_tools(FILE_TOOLS_FULL)