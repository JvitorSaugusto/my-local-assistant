
from langchain_ollama import ChatOllama
from langgraph.graph import add_messages
from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from typing import Annotated, Literal, NotRequired, TypedDict, cast
from pydantic import Field
from backend.api.schemas import GenerateTaskSchema, HeavyAnalysisSchema
from backend.graph.tools import append_to_file, create_git_branch, create_new_file, edit_existing_file, generate_repo_map, git_commit_changes, list_directory_files, read_file_content
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

    
class RouteDecision(BaseModel):
    route: Literal["NORMAL", "CODE", "NOTES"] = Field(
        description="Categoria da intenção principal da mensagem do usuário"
    )
    
    
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    
    thread_id: str
    
    actual_route: str
    heavy_task_id: NotRequired[int | None]
    router_decision: NotRequired[str | None]
    
    summary: str
    enhance_before_heavy: bool
    active_node: str
    enhanced_prompt: str | None
    
    heavy_context: str | None
    
    active_generate_task: GenerateTaskSchema | None
    generate_start_idx: NotRequired[int | None]
    
    workspace_path: str

FILE_TOOLS_SURGICAL = [list_directory_files, read_file_content]
FILE_TOOLS_FULL = [read_file_content, generate_repo_map]
WRITE_AND_GIT_TOOLS = [
    create_git_branch,
    create_new_file,
    edit_existing_file,
    append_to_file,
    git_commit_changes,
    read_file_content,
    generate_repo_map,
    list_directory_files,
]

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


router_structured = load_llm().with_structured_output(RouteDecision).with_config(config={"configurable": { "model": "qwen3:4b", "temperature": 0.0, "max_tokens": 100,}})
standard_llm = ChatOllama(model="gpt-oss:20b", temperature=0.2, num_predict=4096, num_ctx=131072)

code_llm = ChatOllama(model="gpt-oss:20b", temperature=0.1, num_predict=4096, num_ctx=131072)
generate_llm = ChatOllama(model="qwen3-coder:30b", temperature=0.1, num_predict=4096, num_ctx=131072)

note_llm_draft = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=8192, num_ctx=65536, think=True)
note_llm_final = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=24576, num_ctx=65536, think=True)

context_gatherer_llm = ChatOllama(model="qwen3-coder:30b", temperature=0.1, num_predict=8192, num_ctx=131072,)

heavy_llm = ChatOllama(model="deepseek-r1:32b", temperature=0.5, num_predict=16384, num_ctx=49152, reasoning=True)

heavy_llm_structured = heavy_llm.with_structured_output(HeavyAnalysisSchema)

code_llm_with_tools = code_llm.bind_tools(FILE_TOOLS_SURGICAL)
note_llm_draft_with_tools = note_llm_draft.bind_tools(FILE_TOOLS_SURGICAL)
context_gatherer_llm_with_tools = context_gatherer_llm.bind_tools(FILE_TOOLS_FULL)
generate_llm_with_tools = generate_llm.bind_tools(WRITE_AND_GIT_TOOLS)

print(
    "CONTEXT TOOLS:",
    [
        getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        for tool in FILE_TOOLS_FULL
    ],
)

print(
    "GENERATE TOOLS:",
    [
        getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        for tool in WRITE_AND_GIT_TOOLS
    ],
)