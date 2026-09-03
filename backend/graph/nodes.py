from langchain_core.messages import HumanMessage, SystemMessage
from .config import (
    State,
    router_structured,
    standard_llm,
    code_llm,
    note_llm_draft,
    note_llm_final,
    heavy_llm,
)

from .prompts import (
    PROMPT_ENHANCER_NODE_PROMPT,
    ROUTER_NODE_PROMPT,
    STANDARD_NODE_PROMPT,
    CODE_NODE_PROMPT,
    NOTE_NODE_PROMPT,
    HEAVY_NODE_PROMPT,
)

from .utils import detect_explicit_route, strip_leading_heavy_tag, strip_leading_enhancer_tag



def router_node(state: State):
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

    if explicit_route == "HEAVY":
        cleaned_msg = strip_leading_heavy_tag(last_msg)
        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'HEAVY'")

        return {"actual_route": "HEAVY"}
    
    elif explicit_route == "ENHANCER":
        cleaned_msg = strip_leading_enhancer_tag(last_msg)
        state["messages"][-1].content = cleaned_msg

        print("🔀 [ROUTER] Rota explícita: 'ENHANCER'")

        return {"actual_route": "ENHANCER"}

    if len(last_msg) > 600:
        msg_for_router = (
            last_msg[:300]
            + "\n\n... [CONTEÚDO LONGO OCULTO] ...\n\n"
            + last_msg[-300:]
        )
    else:
        msg_for_router = last_msg

    decision = router_structured.invoke([
        SystemMessage(content=ROUTER_NODE_PROMPT),
        HumanMessage(
            content=(
                "<mensagem_do_usuario>\n"
                f"{msg_for_router}\n"
                "</mensagem_do_usuario>"
            )
        ),
    ])

    route = decision.route

    print(
        f"🔀 [ROUTER] "
        f"Rota escolhida pelo LLM: '{route}'"
    )

    return {"actual_route": route}

def enhancer_node(state: State):
    persona = SystemMessage(content=PROMPT_ENHANCER_NODE_PROMPT)
    
    last_message = state["messages"][-1]
    context= [persona, last_message]
    
    response = standard_llm.invoke(context)
    response.name = "GPT-OSS (20B) ENHANCER"
    
    return {"messages": [response]}
    

def standard_node_20b(state: State):
    persona = SystemMessage(content=STANDARD_NODE_PROMPT)
    
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]
    
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
    
    return {"messages": [response]}


def code_node(state: State):
    persona = SystemMessage(content=CODE_NODE_PROMPT)
    
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-6:]
    
    context = [persona]
    
    if actual_summary:
        summary_memory = SystemMessage(content=f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}")
        context.append(summary_memory)
        
    context.extend(recent_messages)
    
    response = code_llm.invoke(context)
    response.name = "GPT-OSS (20B)"
    
    return {"messages": [response]}
    

def note_node(state: State) -> State:
    last_user_message = state["messages"][-1].content

    is_update = (
        "##" in last_user_message
        or "# " in last_user_message
        or "atualiz" in last_user_message.lower()
        or "update" in last_user_message.lower()
    )
    mode = "ATUALIZAÇÃO DE NOTA" if is_update else "GERAÇÃO DE NOTA"

    generation_prompt = (
        f"MODO: {mode}\n\n"
        "CONTEÚDO DO USUÁRIO:\n"
        f"<conteudo>\n{last_user_message}\n</conteudo>\n\n"
        "Transforme o conteúdo acima em uma nota técnica seguindo "
        "todas as regras definidas no prompt do sistema.\n\n"
        "Retorne somente a nota final em Markdown. Comece direto pelo título."
    )

    draft = note_llm_draft.invoke([
        SystemMessage(content=NOTE_NODE_PROMPT),
        HumanMessage(content=generation_prompt),
    ])

    print("\n=== DRAFT ===")
    print("length:", len(draft.content))
    print("\n=== DRAFT META ===")
    print(draft.response_metadata)

    print("\n=== DRAFT KWARGS ===")
    print(draft.additional_kwargs)

    refinement_prompt = f"""
        Revise e aprimore a nota técnica abaixo para produzir a versão final.

        Mantenha exatamente o mesmo assunto e preserve as informações corretas.

        Durante a revisão:

        - corrija informações tecnicamente incorretas ou imprecisas;
        - evite afirmações absolutas quando o comportamento depender do contexto;
        - aprofunde explicações que estejam superficiais;
        - explique conceitos auxiliares importantes;
        - explique o "porquê" das decisões técnicas;
        - adicione exemplos de código quando ajudarem a compreender o conceito;
        - adicione exemplos diferentes quando isso trouxer valor real;
        - diferencie conceitos que possam ser confundidos;
        - melhore a organização e a sequência da explicação;
        - elimine redundâncias;
        - inclua limitações, pegadinhas e erros comuns relevantes.

        Preserve o conteúdo correto do rascunho.

        Não troque o assunto.
        Não invente APIs, métodos, comportamentos ou informações.
        Não adicione conteúdo artificialmente apenas para aumentar o tamanho.

        <nota>
        {draft.content}
        </nota>

        Retorne somente a versão final da nota em Markdown.
        """

    final_response = note_llm_final.invoke([
        HumanMessage(content=refinement_prompt),
    ])
    
    print(note_llm_final)
    print(note_llm_final.__dict__)

    print("\n=== FINAL RESPONSE ===")
    print("length:", len(final_response.content))
    print("done_reason:", final_response.response_metadata.get("done_reason"))
    print("CONTENT:", repr(final_response.content))
    print("METADATA:", final_response.response_metadata)

    if not final_response.content.strip():
        final_response = draft
        
    if not draft.content.strip():
        final_response = note_llm_final.invoke([
            HumanMessage(content=(
                "Crie a nota final diretamente a partir deste pedido:\n\n"
                f"{last_user_message}"
            ))
        ])

    final_response.name = "Qwen3 Notas (30B)"

    return {"messages": [final_response]}

def heavy_task_node_70b(state: State):
    persona = SystemMessage(content=HEAVY_NODE_PROMPT)
    
    actual_summary = state.get("summary", "")
    recent_messages = state["messages"][-10:]
    context = [persona]
    
    if actual_summary:
        summary_memory = SystemMessage(content=f"RESUMO DOS ASSUNTOS ANTIGOS DESTA CONVERSA:\n{actual_summary}")
        context.append(summary_memory)
        
    context.extend(recent_messages)
    
    response = heavy_llm.invoke(context)
    response.name = "DeepSeek R1 (70B)"
    
    return {
        "messages": [response],
    }

def route_decision(state: State):
    destiny = state.get("actual_route", "NORMAL")
    
    if destiny == "CODE":
        return "code_node"
    elif destiny == "HEAVY":
        return "heavy_task_node_70b"
    elif destiny == "NOTES":
        return "note_node"
    elif destiny == "ENHANCER":
        return "enhancer_node"
    else:
        return "standard_node_20b"

def check_context_limit(state: State):
    messages_qnt = len(state["messages"])

    if messages_qnt > 10 and (messages_qnt - 1) % 10 == 0:
        return "go_to_summarize"
        
    return "go_to_router"

def summarize_node(state: State):
    actual_summary = state.get("summary", "")
    all_messages = state["messages"]
    
    recent_messages = all_messages[-10:] 
    
    if actual_summary:
        prompt = f"Resumo atual da conversa: {actual_summary}\n\nLeia as novas mensagens acima e atualize o resumo para incluir esses novos assuntos. Mantenha em apenas um parágrafo conciso."
    else:
        prompt = "Resuma o assunto principal desta conversa acima em apenas um parágrafo conciso."
        
    order = HumanMessage(content=prompt)
    
    response = standard_llm.invoke(recent_messages + [order])
    
    return {"summary": response.content}