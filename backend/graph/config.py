
from langchain_ollama import ChatOllama
from langgraph.graph import add_messages
from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from typing import Annotated, Literal, NotRequired, TypedDict, cast
from pydantic import Field
from backend.api.schemas import GenerateTaskSchema, HeavyAnalysisSchema
from backend.graph.tools import append_to_file, create_git_branch, create_new_file, create_pdf_file, edit_existing_file, batch_edit_file, generate_repo_map, read_file_chunk, replace_in_file, search_in_file, search_codebase, list_directory_files, read_file_content, validate_python_syntax, write_markdown_file
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
    gatherer_tool_trace: list[dict]
    
    active_generate_task: GenerateTaskSchema | None
    generate_start_idx: NotRequired[int | None]
    
    workspace_path: str

FILE_TOOLS_SURGICAL = [list_directory_files, read_file_content, read_file_chunk, search_in_file, search_codebase]
FILE_TOOLS_FULL = [read_file_content, generate_repo_map, read_file_chunk, search_in_file, search_codebase]
WRITE_AND_GIT_TOOLS = [
    create_git_branch,
    create_new_file,
    edit_existing_file,
    batch_edit_file,
    append_to_file,
    replace_in_file,
    write_markdown_file,
    create_pdf_file,
    read_file_content,
    generate_repo_map,
    list_directory_files,
    read_file_chunk,
    search_in_file,
    search_codebase,
    validate_python_syntax,
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
# Janela de contexto do agente Generate. O Ollama CORTA o excesso do prompt sem avisar;
# o sistema estima o tamanho do prompt e avisa quando chegar perto deste valor.
GENERATE_NUM_CTX = 131072
# Quantas vezes o agente pode corrigir o próprio resultado quando a verificação automática falha.
MAX_VERIFY_RETRIES = 2
# True: tarefas em modo livre terminam em 'review' e só viram 'completed' após aprovação no painel.
REVIEW_FREE_TASKS = True

generate_llm = ChatOllama(model="qwen3-coder:30b", temperature=0.1, num_predict=8192, num_ctx=GENERATE_NUM_CTX)

note_llm_draft = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=8192, num_ctx=65536)
note_llm_final = ChatOllama(model="hf.co/unsloth/Qwen3-30B-A3B-Thinking-2507-GGUF:Q4_K_M", temperature=0.6, num_predict=24576, num_ctx=65536)

context_gatherer_llm = ChatOllama(model="qwen3-coder:30b", temperature=0.1, num_predict=8192, num_ctx=131072,)

heavy_llm = ChatOllama(model="qwen3-coder:30b", temperature=0.3, num_predict=16384, num_ctx=49152)

heavy_llm_structured = heavy_llm.with_structured_output(HeavyAnalysisSchema)

code_llm_with_tools = code_llm.bind_tools(FILE_TOOLS_SURGICAL)
note_llm_draft_with_tools = note_llm_draft.bind_tools(FILE_TOOLS_SURGICAL)
context_gatherer_llm_with_tools = context_gatherer_llm.bind_tools(FILE_TOOLS_FULL)
generate_llm_with_tools = generate_llm.bind_tools(WRITE_AND_GIT_TOOLS)
