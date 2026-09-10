import time

from langchain_core.messages import HumanMessage, SystemMessage
from .config import (
    State,
    router_structured,
    standard_llm,
    code_llm_with_tools,
    note_llm_draft_with_tools,
    note_llm_final,
    context_gatherer_llm_with_tools,
    heavy_llm,
)

from .prompts import (
    CONTEXT_GATHERER_PROMPT,
    PROMPT_ENHANCER_NODE_PROMPT,
    ROUTER_NODE_PROMPT,
    STANDARD_NODE_PROMPT,
    CODE_NODE_PROMPT,
    NOTE_NODE_PROMPT,
    HEAVY_NODE_PROMPT,
)

from .utils import detect_explicit_route, strip_leading_tags


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
    persona = SystemMessage(content=STANDARD_NODE_PROMPT)
    
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]
    
    if state.get("enhanced_prompt"):
         recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))
    
    context = [persona]
    
    if actual_summary:
        summary_memory = SystemMessage(content=f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}")
        context.append(summary_memory)
        
    context.extend(recent_messages)
    
    response = standard_llm.invoke(context)
    print("=== STANDARD ===")
    print("length:", len(response.content))
    print("metadata:", response.response_metadata)
    print("content:", repr(response.content[-500:]))
    response.name = "GPT-OSS (20B)"
    
    return {"messages": [response], "enhanced_prompt": None}


def code_node(state: State):
    persona = SystemMessage(content=CODE_NODE_PROMPT)
    
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]
    
    if state.get("enhanced_prompt"):
        recent_messages[-1] = HumanMessage(content=state.get("enhanced_prompt"))
    
    context = [persona]
    
    if actual_summary:
        summary_memory = SystemMessage(content=f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}")
        context.append(summary_memory)
        
    context.extend(recent_messages)
    
    response = code_llm_with_tools.invoke(context)
    response.name = "GPT-OSS (20B) CODE"
    
    return {
        "messages": [response],
        "active_node": "code_node",
        "enhanced_prompt": None
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
    persona = SystemMessage(
        content=CONTEXT_GATHERER_PROMPT
    )

    actual_summary = state.get("summary", "")

    last_human_idx = 0
    for i in range(len(state["messages"]) - 1, -1, -1):
        if state["messages"][i].type == "human":
            last_human_idx = i
            break

    start_idx = max(0, last_human_idx - 4)
    recent_messages = state["messages"][start_idx:].copy()

    if state.get("enhanced_prompt"):
        enhanced = HumanMessage(
            content=state["enhanced_prompt"]
        )

        for index in range(len(recent_messages) - 1, -1, -1):
            if recent_messages[index].type == "human":
                recent_messages[index] = enhanced
                break

    context = [persona]

    if actual_summary:
        context.append(
            SystemMessage(
                content=f"RESUMO DA CONVERSA:\n{actual_summary}"
            )
        )

    context.extend(recent_messages)

    response = context_gatherer_llm_with_tools.invoke(context)

    response.name = "Qwen3-Coder (Context Gatherer)"

    print("\n===== CONTEXT GATHERER =====")
    print("TOOL_CALLS:", response.tool_calls)

    if response.content:
        print("CONTENT LENGTH:", len(response.content))

    print("============================\n")

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

def heavy_analyzer_node(state: State):
    persona = SystemMessage(content=HEAVY_NODE_PROMPT)
    actual_summary = state.get("summary", "")
    dossier = state.get("heavy_context", "")

    user_request = None
    for message in reversed(state["messages"]):
        if message.type == "human":
            user_request = message
            break

    context = [persona]

    if actual_summary:
        context.append(SystemMessage(content=f"RESUMO DA CONVERSA:\n{actual_summary}"))
        
    if dossier and dossier.strip():
        context.append(
            SystemMessage(
                content=(
                    "--- DOSSIÊ TÉCNICO (DADOS COLETADOS DO SISTEMA) ---\n"
                    f"{dossier}\n"
                    "---------------------------------------------------\n"
                    "AVISO DE SISTEMA: Se o usuário pedir para analisar arquivos ou repositórios, "
                    "assuma que os dados do Dossiê acima são as leituras reais. "
                    "NÃO diga que você não tem acesso ao sistema ou não pode ler arquivos. "
                    "Apenas forneça a análise com base no Dossiê."
                )
            )
        )

    if user_request:
        context.append(user_request)

    print(f"\n[⏳ AGUARDE] DeepSeek R1 processando {len(context)} mensagens...")
    
    start_time = time.time()
    
    response = heavy_llm.invoke(context)
    
    elapsed_time = time.time() - start_time
    print(f"TEMPO DE RESPOSTA DO R1: {elapsed_time:.2f} segundos")
    response.name = "DeepSeek R1 (32B)"

    print("\n===== HEAVY ANALYZER =====")
    print("CONTENT LENGTH:", len(response.content))
    print("==========================\n")

    return {
        "messages": [response],
        "heavy_context": None,
        "enhanced_prompt": None,
        "active_node": "heavy_analyzer_node",
    }
    
def route_decision(state: State):
    destiny = state.get("actual_route", "NORMAL")
    if destiny == "CODE": return "code_node"
    elif destiny == "HEAVY": return "context_gatherer_node"
    elif destiny == "NOTES": return "note_draft_node"
    elif destiny == "ENHANCER": return "enhancer_node"
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