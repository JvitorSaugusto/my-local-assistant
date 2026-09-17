import re
import time
from backend.database.config import async_session_env
from backend.database.models import TaskModel
from langchain_core.messages import AIMessage
from sqlalchemy import select, update
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import HumanMessage, SystemMessage
from .config import (
    State,
    router_structured,
    standard_llm,
    code_llm_with_tools,
    note_llm_draft_with_tools,
    note_llm_final,
    context_gatherer_llm_with_tools,
    heavy_llm_structured,
    generate_llm_with_tools,
)

from .prompts import (
    CONTEXT_GATHERER_PROMPT,
    PROMPT_ENHANCER_NODE_PROMPT,
    ROUTER_NODE_PROMPT,
    STANDARD_NODE_PROMPT,
    CODE_NODE_PROMPT,
    NOTE_NODE_PROMPT,
    HEAVY_NODE_PROMPT,
    GENERATE_NODE_PROMPT
)

from .utils import detect_explicit_route, strip_leading_tags


WRITE_TOOL_NAMES = {"create_new_file", "edit_existing_file", "append_to_file", "git_commit_changes"}

def _has_write_call(messages) -> bool:
    return any(
        call["name"] in WRITE_TOOL_NAMES
        for msg in messages
        if getattr(msg, "tool_calls", None)
        for call in msg.tool_calls
    )
    
def build_system_context(*parts: str | None) -> SystemMessage:
    """Junta múltiplas partes de contexto de sistema em uma única SystemMessage, separadas por um divisor."""
    valid_parts = [p.strip() for p in parts if p and p.strip()]
    return SystemMessage(content="\n\n---\n\n".join(valid_parts))

def router_node(state: State):
    if state.get("enhanced_prompt"):
        last_msg = state["enhanced_prompt"]
    else:
        raw_content = state["messages"][-1].content

        if isinstance(raw_content, list):
            last_msg = " ".join(
                str(item.get("text", ""))
                for item in raw_content
                if isinstance(item, dict) and "text" in item
            )
        else:
            last_msg = str(raw_content)

    explicit_route = detect_explicit_route(last_msg)
    
    if explicit_route == "ENHANCER_HEAVY":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'ENHANCER → HEAVY'")

        return {
            "actual_route": "ENHANCER",
            "enhance_before_heavy": True,
        }
        
    if explicit_route == "HEAVY":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'HEAVY'")

        return {
            "actual_route": "HEAVY",
            "enhance_before_heavy": False,
        }
        
    if explicit_route == "ENHANCER":
        cleaned_msg = strip_leading_tags(last_msg)

        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'ENHANCER'")

        return {
            "actual_route": "ENHANCER",
            "enhance_before_heavy": False,
        }
    
    if state.get("active_generate_task"):
        print("🔀 [ROUTER] Rota de Execução em Background: 'GENERATE_EXECUTE'")
        return {
            "actual_route": "GENERATE_EXECUTE",
            "enhance_before_heavy": False,
        }

    if "@generate" in last_msg.lower():
        print("🔀 [ROUTER] Rota de Despacho: 'GENERATE_DISPATCH'")
        return {
            "actual_route": "GENERATE_DISPATCH",
            "enhance_before_heavy": False,
        }
        
    if len(last_msg) > 600:
        msg_for_router = (
            last_msg[:300]
            + "\n\n... [CONTEÚDO LONGO OCULTO] ...\n\n"
            + last_msg[-300:]
        )
    else:
        msg_for_router = last_msg
        
    recent_messages = state["messages"][-5:-1] 
    
    history_str = ""
    for m in recent_messages:
        if m.type == "system": 
            continue
            
        role = "Usuário" if m.type == "human" else "Assistente"
        text = m.content if m.content else "[Ação: Leitura de Arquivo/Pasta]"
        
        content_trunc = text[:250] + "... [cortado]" if len(text) > 250 else text
        history_str += f"{role}: {content_trunc}\n"

    decision = router_structured.invoke([
        SystemMessage(content=ROUTER_NODE_PROMPT),
        HumanMessage(
            content=(
                "<contexto_da_conversa_recente>\n"
                f"{history_str}\n"
                "</contexto_da_conversa_recente>\n\n"
                "<mensagem_do_usuario>\n"
                f"{msg_for_router}\n"
                "</mensagem_do_usuario>\n\n"
                "Com base no contexto acima, para qual rota esta NOVA mensagem deve ir?"
            )
        ),
    ])

    route = decision.route

    print(
        f"🔀 [ROUTER] "
        f"Rota escolhida pelo LLM: '{route}'"
    )

    return {
        "actual_route": route,
        "enhance_before_heavy": False,
    }

def enhancer_node(state: State):
    persona = SystemMessage(content=PROMPT_ENHANCER_NODE_PROMPT)
    
    last_message = state["messages"][-1]
    context= [persona, last_message]
    
    response = standard_llm.invoke(context)
    response.name = "GPT-OSS (20B) ENHANCER"
    
    print("GPT-OSS (20B) ENHANCER")
    
    return {"enhanced_prompt": response.content,}
    
def after_enhancer_route(state: State):
    if state.get("enhance_before_heavy"): return "context_gatherer_node" # Redireciona pro Coletor
    return "router_node"

def standard_node_20b(state: State):
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]

    if state.get("enhanced_prompt"):
         recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    context = [
        build_system_context(
            STANDARD_NODE_PROMPT,
            f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}" if actual_summary else None,
        )
    ]

    context.extend(recent_messages)

    response = standard_llm.invoke(context)
    print("=== STANDARD ===")
    print("length:", len(response.content))
    print("metadata:", response.response_metadata)
    print("content:", repr(response.content[-500:]))
    response.name = "GPT-OSS (20B)"

    return {"messages": [response], "enhanced_prompt": None}

def code_node(state: State):
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]
    
    workspace_path = state.get("workspace_path", "Diretório não informado")

    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    prompt_with_workspace = f"{CODE_NODE_PROMPT}\n\n[CONTEXTO DO AMBIENTE]\nO caminho raiz do workspace atual é: {workspace_path}"

    context = [
        build_system_context(
            prompt_with_workspace,
            f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}" if actual_summary else None,
        )
    ]

    context.extend(recent_messages)

    response = code_llm_with_tools.invoke(context)
    response.name = "GPT-OSS (20B) CODE"

    return {
        "messages": [response],
        "active_node": "code_node",
        "enhanced_prompt": None
    }

async def generate_dispatch_node(state: State, config: RunnableConfig):
    last_msg = state["messages"][-1].content.lower()
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id", "thread_ausente")

    match = re.search(r'@generate\s+(.*)', last_msg)
    target_ids = []
    if match:
        target_ids = [int(x) for x in re.findall(r'\d+', match.group(1))]

    from tasks import run_generate_task

    dispatched_count = 0

    async with async_session_env() as db:
        stmt = select(TaskModel).where(
            TaskModel.thread_id == thread_id,
            TaskModel.status == "pending"
        )

        if target_ids:
            stmt = stmt.where(TaskModel.id.in_(target_ids))

        result = await db.execute(stmt)
        tasks_to_run = result.scalars().all()

        if not tasks_to_run:
            return {
                "messages": [
                    AIMessage(
                        content="Nenhuma tarefa pendente foi encontrada no banco para executar."
                    )
                ],
                "active_node": "generate_dispatch_node",
            }

        workspace_path = state.get("workspace_path")

        if not workspace_path:
            return {
                "messages": [
                    AIMessage(
                        content="Nenhum diretório de trabalho foi definido para esta conversa."
                    )
                ],
                "active_node": "generate_dispatch_node",
            }

        for task in tasks_to_run:

            task_dict = {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "files": task.files,
                "reason": task.reason,
                "priority": task.priority,
                "status": "queued",
                "repo_path": workspace_path,
            }

            run_generate_task.delay(thread_id, task_dict)

            task.status = "queued"
            dispatched_count += 1

        await db.commit()

    msg_retorno = (
        f"{dispatched_count} tarefa(s) enviada(s) para execução "
        "em background (Celery)."
    )

    return {
        "messages": [AIMessage(content=msg_retorno)],
        "active_node": "generate_dispatch_node",
    } 
    
async def generate_node(state: State):
    actual_summary = state.get("summary", "")
    
    generate_start_idx = state.get("generate_start_idx")
    
    if generate_start_idx is None:
        last_human_idx = 0
        for i in range(len(state["messages"]) - 1, -1, -1):
            if state["messages"][i].type == "human":
                last_human_idx = i
                break
        generate_start_idx = last_human_idx
        
    recent_messages = state["messages"][generate_start_idx:].copy()
    task = state.get("active_generate_task")

    workspace = state.get("workspace_path")
    branch_context = None
    if workspace:
        repo = __import__("pathlib").Path(workspace).resolve()
        try:
            import subprocess
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=10,
            )
            current_branch = branch_result.stdout.strip()
            if current_branch and current_branch not in {"main", "master"}:
                branch_context = (
                    "STATUS DA BRANCH DO WORKSPACE: "
                    f"a branch atual é '{current_branch}'. "
                    "Uma branch de trabalho já está ativa. NÃO chame "
                    "'create_git_branch' novamente nesta execução; prossiga "
                    "para a próxima etapa da tarefa."
                )
        except (OSError, subprocess.SubprocessError):
            pass

    if state.get("enhanced_prompt"):
        for i in range(len(recent_messages) - 1, -1, -1):
            if recent_messages[i].type == "human":
                recent_messages[i] = HumanMessage(content=state["enhanced_prompt"])
                break

    context = [
        build_system_context(
            GENERATE_NODE_PROMPT,
            f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}" if actual_summary else None,
            branch_context,
            (
                "TAREFA DE IMPLEMENTAÇÃO:\n\n"
                f"{task.model_dump_json(indent=2)}"
            ) if task else None,
        )
    ]

    context.extend(recent_messages)

    response = await generate_llm_with_tools.ainvoke(context)
    response.name = "Qwen3-Coder (Generate)"
    
    print("\n===== GENERATE =====")
    print("TOOL_CALLS:", response.tool_calls)
    if response.content:
        print("CONTENT:\n", response.content)
    print("====================\n")

    messages_to_return = [response]
    is_final_response = not bool(response.tool_calls)

    if task and is_final_response:
        all_messages_this_run = recent_messages + messages_to_return
        wrote_something = _has_write_call(all_messages_this_run)
        
        content_str = str(response.content).strip().upper() if response.content else ""
        reported_ambiguous = content_str.startswith("TAREFA AMBÍGUA")

        if not wrote_something and not reported_ambiguous:
            print("⚠️ [GENERATE] Tentativa de finalizar sem ação. Aplicando Nudge...")
            nudge = HumanMessage(content=(
                "Você não chamou nenhuma ferramenta de escrita e não editou nenhum "
                "arquivo. Se pretende fazer uma alteração, chame agora a ferramenta "
                "necessária (create_git_branch, depois edit_existing_file/create_new_file). "
                "Se a tarefa não pode ser concluída com segurança, responda começando "
                "EXATAMENTE com 'TAREFA AMBÍGUA:' e explique o motivo."
            ))
            
            response2 = await generate_llm_with_tools.ainvoke(context + [response, nudge])
            response2.name = "Qwen3-Coder (Generate)"
            
            print("\n===== GENERATE (NUDGE) =====")
            print("TOOL_CALLS:", response2.tool_calls)
            if response2.content:
                print("CONTENT:\n", response2.content)
            print("====================\n")
            
            messages_to_return.extend([nudge, response2])
            
            is_final_response = not bool(response2.tool_calls)
            all_messages_this_run = recent_messages + messages_to_return
            wrote_something = _has_write_call(all_messages_this_run)
            content_str2 = str(response2.content).strip().upper() if response2.content else ""
            reported_ambiguous = content_str2.startswith("TAREFA AMBÍGUA")

        if is_final_response:
            final_status = "completed" if (wrote_something or reported_ambiguous) else "failed"
            
            if final_status == "failed":
                print("❌ [GENERATE] Falhou em executar ações mesmo após o nudge. Marcando como failed.")
                
            async with async_session_env() as db:
                stmt = (
                    update(TaskModel)
                    .where(TaskModel.id == task.id)
                    .values(status=final_status)
                )
                await db.execute(stmt)
                await db.commit()

    return {
        "messages": messages_to_return,
        "active_node": "generate_node",
        "enhanced_prompt": None,
        "active_generate_task": None if is_final_response else task
    }
    
def note_draft_node(state: State) -> State:
    persona = SystemMessage(content=NOTE_NODE_PROMPT)

    recent_messages = state["messages"][-6:]

    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))

    last_user_message = recent_messages[-1].content if recent_messages else ""

    is_update = (
        "##" in last_user_message or "# " in last_user_message
        or "atualiz" in last_user_message.lower() or "update" in last_user_message.lower()
    )
    mode = "ATUALIZAÇÃO DE NOTA" if is_update else "GERAÇÃO DE NOTA"

    instruction = HumanMessage(content=(
        f"MODO: {mode}\n\n"
        "Se a nota mencionar um projeto, diretório ou arquivo real, você DEVE "
        "chamar `list_directory_files` e/ou `read_file_content` antes de escrever "
        "qualquer conteúdo técnico sobre ele — mesmo que você acredite já saber "
        "a estrutura pelo histórico da conversa. Antes de cada chamada, escreva "
        "uma linha 'Raciocínio: [motivo]'. Nunca escreva nomes de arquivos, "
        "modelos ou tecnologias que não tenham sido confirmados por uma chamada "
        "de ferramenta ou pela mensagem do usuário.\n\n"
        "Transforme o conteúdo acima em uma nota técnica seguindo todas as "
        "regras do prompt do sistema.\n\nRetorne somente a nota final em Markdown."
    ))

    context = [persona] + recent_messages + [instruction]

    draft = note_llm_draft_with_tools.invoke(context)
    draft.name = "Qwen3 Notas Draft"

    print("\n=== DRAFT NODE ===")
    print("Possui tool calls?", bool(draft.tool_calls))
    if draft.content:
        print("Tamanho do rascunho:", len(draft.content))

    return {
        "messages": [draft],
        "active_node": "note_draft_node",
        "enhanced_prompt": None
    }
    
def note_refine_node(state: State) -> State:
    draft_msg = state["messages"][-1]
    draft_content = draft_msg.content

    print("\n=== REFINE NODE ===")

    persona = SystemMessage(content=NOTE_NODE_PROMPT)

    if not draft_content or not draft_content.strip():
        print("Aviso: Rascunho vazio chegou no Refine.")
        recent_messages = state["messages"][-6:]
        final_response = note_llm_final.invoke([persona] + recent_messages)
    else:
        refinement_prompt = f"""
        Aqui está um rascunho de nota (uso interno, não deve aparecer na sua resposta):

        <rascunho>
        {draft_content}
        </rascunho>

        Reescreva mantendo tudo que já está correto e adicionando profundidade
        onde fizer sentido (segundo exemplo, o "porquê" de decisões técnicas,
        diferenciação de conceitos). Não invente informações que não estejam
        no rascunho, no histórico da conversa ou no conteúdo lido pelas ferramentas.

        Responda somente com a nota final e reescrita, em Markdown, começando
        direto com '# '. Não inclua o rascunho nem comentários sobre o processo.
        """

        final_response = note_llm_final.invoke([
            persona,
            HumanMessage(content=refinement_prompt),
        ])

        if not final_response.content.strip():
            final_response = draft_msg

    final_response.name = "Qwen3 Notas Final (30B)"
    return {"messages": [final_response]}

def context_gatherer_node(state: State):
    actual_summary = state.get("summary", "")

    last_human_idx = 0
    for i in range(len(state["messages"]) - 1, -1, -1):
        if state["messages"][i].type == "human":
            last_human_idx = i
            break

    recent_messages = state["messages"][last_human_idx:].copy()

    if state.get("enhanced_prompt"):
        enhanced = HumanMessage(
            content=state["enhanced_prompt"]
        )

        for index in range(len(recent_messages) - 1, -1, -1):
            if recent_messages[index].type == "human":
                recent_messages[index] = enhanced
                break

    workspace = state.get("workspace_path")

    context = [
        build_system_context(
            CONTEXT_GATHERER_PROMPT,
            f"RESUMO DA CONVERSA:\n{actual_summary}" if actual_summary else None,
            (
                "Ao usar 'list_directory_files' ou 'read_file_content', envie SEMPRE "
                "caminhos relativos à raiz do projeto (ex: 'tasks.py', 'backend/main.py'). "
                "O sistema já resolve isso automaticamente contra o workspace correto — "
                "não é necessário (e não deve) incluir o caminho completo do disco."
            ) if workspace else None,
        )
    ]

    context.extend(recent_messages)

    response = context_gatherer_llm_with_tools.invoke(context)

    response.name = "Qwen3-Coder (Context Gatherer)"

    print("\n===== CONTEXT GATHERER =====")
    print("TOOL_CALLS:", response.tool_calls)

    if response.content:
        print("CONTENT LENGTH:", len(response.content))
        print("CONTENT:")
        print(response.content)

    print("============================\n")
    from .config import FILE_TOOLS_FULL
    
    print(
    "CONTEXT GATHERER TOOL NAMES:",
    [
        getattr(tool, "name", getattr(tool, "__name__", str(tool)))
        
        for tool in FILE_TOOLS_FULL
    ],
)

    if response.tool_calls:
        return {
            "messages": [response],
            "active_node": "context_gatherer_node",
            "enhanced_prompt": None,
        }

    return {
        "heavy_context": response.content,
        "active_node": "context_gatherer_node",
        "enhanced_prompt": None,
    }

async def heavy_analyzer_node(state: State, config: RunnableConfig):
    actual_summary = state.get("summary", "")
    dossier = state.get("heavy_context", "")
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id", "thread_ausente")

    user_request = None
    for message in reversed(state["messages"]):
        if message.type == "human":
            user_request = message
            break

    context = [
        build_system_context(
            HEAVY_NODE_PROMPT,
            f"RESUMO DA CONVERSA:\n{actual_summary}" if actual_summary else None,
            (
                "--- DOSSIÊ TÉCNICO (DADOS COLETADOS DO SISTEMA) ---\n"
                f"{dossier}\n"
                "---------------------------------------------------\n"
                "AVISO DE SISTEMA: Se o usuário pedir para analisar arquivos ou repositórios, "
                "assuma que os dados do Dossiê acima são as leituras reais. "
                "NÃO diga que você não tem acesso ao sistema ou não pode ler arquivos. "
                "Apenas forneça a análise com base no Dossiê."
            ) if dossier and dossier.strip() else None,
        )
    ]

    if user_request:
        context.append(user_request)

    print(f"\n[⏳ AGUARDE] DeepSeek R1 processando {len(context)} mensagens...")
    
    start_time = time.time()
    
    result = await heavy_llm_structured.ainvoke(context)

    elapsed_time = time.time() - start_time

    print(
        f"TEMPO DE RESPOSTA DO R1: "
        f"{elapsed_time:.2f} segundos"
    )

    response = AIMessage(
        content=result.analysis,
        name="DeepSeek R1 (32B)",
    )

    if result.tasks:
        async with async_session_env() as db:
            try:
                for task in result.tasks:
                    description = (
                        f"**Objetivo:**\n{task.objective}\n\n"
                        f"**Localização Alvo:**\n{task.target}\n\n"
                        f"**Lógica da Alteração (Instruções Detalhadas):**\n{task.logic}\n\n"
                        f"**Restrições do Usuário:**\n{task.constraints}"
                    )
                    
                    new_task = TaskModel(
                        thread_id=thread_id,
                        title=task.title,
                        description=description,
                        files=task.files,
                        reason=task.reason,
                        priority=task.priority,
                        status="pending"
                    )
                    db.add(new_task)
                
                await db.commit()
                
            except Exception as e:
                await db.rollback()
                print(f"Erro ao salvar as tasks: {e}")
                raise e


    print("\n===== HEAVY ANALYZER =====")
    print("TASKS GERADAS E SALVAS:", len(result.tasks))
    print("CONTENT LENGTH:", len(result.analysis))
    print("==========================\n")
    
    for task in result.tasks:
        print(f"\n--- TAREFA GERADA: {task.title} ---")
        print("files:", task.files)
        print("description:", description)
        print("---\n")

    return {
        "messages": [response],
        "heavy_context": None,
        "enhanced_prompt": None,
        "active_node": "heavy_analyzer_node",

    }
    
def route_decision(state: State):
    destiny = state.get("actual_route", "NORMAL")
    if destiny == "CODE": return "code_node"
    elif destiny == "HEAVY": 
        workspace = state.get("workspace_path", "")
        
        if workspace is None:
            workspace = ""
            
        if workspace.strip():
            print("🔀 [EDGE] Rota HEAVY com tools. Indo para: context_gatherer_node")
            return "context_gatherer_node"
        
        else:
            print("🔀 [EDGE] Rota HEAVY sem tools. Indo para: heavy_analyzer_node")
            return "heavy_analyzer_node"
        
    elif destiny == "NOTES": return "note_draft_node"
    elif destiny == "ENHANCER": return "enhancer_node"
    elif destiny == "GENERATE_DISPATCH": return "generate_dispatch_node" # Disparado pelo seu texto
    elif destiny == "GENERATE_EXECUTE": return "generate_node" # Disparado pelo Celery
    return "standard_node_20b"

def check_context_limit(state: State):
    meaningful_count = 0
    
    for msg in state["messages"]:
        if msg.type == "tool":
            continue
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            continue
            
        meaningful_count += 1

    if meaningful_count > 10 and (meaningful_count - 1) % 10 == 0:
        print(f"\n[🔄 RESUMO] Limite de {meaningful_count} mensagens reais atingido. Gerando resumo...")
        return "go_to_summarize"
        
    return "go_to_router"

def summarize_node(state: State):
    actual_summary = state.get("summary", "")
    all_messages = state["messages"]
    
    meaningful_messages = []
    
    for msg in all_messages:
        if msg.type == "tool":
            continue
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            continue
            
        meaningful_messages.append(msg)
    
    recent_messages = meaningful_messages[-10:] 
    
    if actual_summary:
        prompt = f"Resumo atual da conversa: {actual_summary}\n\nLeia as novas mensagens acima e atualize o resumo para incluir esses novos assuntos. Mantenha em apenas um parágrafo conciso."
    else:
        prompt = "Resuma o assunto principal desta conversa acima em apenas um parágrafo conciso."
        
    order = HumanMessage(content=prompt)
    
    response = standard_llm.invoke(recent_messages + [order])
    
    return {"summary": response.content, "enhanced_prompt": None}

def return_tool_message(state: State):
    return state["active_node"]
