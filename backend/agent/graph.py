from typing import Annotated, TypedDict,NotRequired
from langchain_core.messages import BaseMessage
from langchain_ollama import ChatOllama
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agent.router_model_config import router_structured
from backend.agent.agent import load_llm
from backend.agent.prompts import CODE_NODE_PROMPT, HEAVY_NODE_PROMPT, NOTE_NODE_PROMPT, ROUTER_NODE_PROMPT, STANDARD_NODE_PROMPT



class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    actual_route: str
    heavy_task_id: NotRequired[int | None]
    router_decision: NotRequired[str | None]
    summary: str
    

router_llm = load_llm().with_config(config={"configurable": {"model": "llama3.2:1b", "temperature": 0.0}})
standard_llm = load_llm().with_config(config={"configurable": {"model": "gpt-oss:20b", "temperature": 0.2, "max_tokens": 8192,}})
code_llm = load_llm().with_config(config={"configurable": {"model": "qwen3-coder:30b", "temperature": 0.1, "max_tokens": 8192,}})
note_llm_draft = ChatOllama(model="qwen3:30b-a3b", temperature=0.2, num_predict=8192, num_ctx=32768, think=True,)
note_llm_final = ChatOllama(model="qwen3:30b-a3b", temperature=0.2, num_predict=24576, num_ctx=32768, think=True,)
heavy_llm = load_llm().with_config(config={"configurable": {"model": "DeepSeek-R1:70b", "temperature": 0.1, "max_tokens": 16384,}})


def detect_explicit_route(text: str) -> str | None:
    text_lower = text.lower().strip()

    if "@heavy" in text_lower:
        return "HEAVY"

    note_triggers = [
        "crie uma nota",
        "criar uma nota",
        "faça uma nota",
        "fazer uma nota",
        "gere uma nota",
        "gerar uma nota",

        "crie uma anotação",
        "criar uma anotação",
        "faça uma anotação",
        "fazer uma anotação",
        "gere uma anotação",
        "gerar uma anotação",

        "crie uma documentação",
        "criar uma documentação",
        "faça uma documentação",
        "fazer uma documentação",
        "gere uma documentação",
        "gerar uma documentação",

        "documente isso",
        "documentar isso",
        "transforme em documentação",
        "transformar em documentação",
        "transforme isso em documentação",

        "transforme em nota",
        "transformar em nota",
        "transforme isso em nota",
        "transformar isso em nota",

        "para o notion",
        "pro notion",
        "para notion",
        "no notion",
        "anotação no notion",
        "nota no notion",
        "documentação no notion",
    ]

    if any(trigger in text_lower for trigger in note_triggers):
        return "NOTES"

    code_actions = [
        "gere ",
        "gerar ",
        "crie ",
        "criar ",
        "faça ",
        "fazer ",

        "implemente",
        "implementar",

        "altere ",
        "alterar ",
        "modifique ",
        "modificar ",

        "corrija ",
        "corrigir ",
        "conserte ",
        "consertar ",

        "refatore",
        "refatorar",

        "otimize ",
        "otimizar ",

        "debugue",
        "debugar",
        "debug ",
        "encontre o bug",
        "encontre o erro",

        "adicione ao código",
        "adicionar ao código",
        "adicione uma função",
        "adicionar uma função",
        "adicione um endpoint",
        "adicionar um endpoint",
    ]

    code_objects = [
        "código",
        "codigo",
        "script",
        "snippet",

        "função",
        "funcao",
        "function",
        "método",
        "metodo",

        "classe",
        "class",
        "objeto",

        "endpoint",
        "api",
        "api rest",
        "controller",
        "service",
        "middleware",

        "query",
        "consulta sql",
        "sql",
        "orm",

        "componente",
        "component",
        "html",
        "css",
        "javascript",
        "typescript",
        "react",
        "next.js",
        "nextjs",

        "arquivo python",
        "arquivo html",
        "arquivo css",
        "arquivo js",
        "arquivo ts",
        "arquivo javascript",
        "arquivo typescript",
    ]

    has_code_action = any(action in text_lower for action in code_actions)
    has_code_object = any(obj in text_lower for obj in code_objects)

    if has_code_action and has_code_object:
        return "CODE"

    explicit_code_triggers = [
        "escreva o código",
        "escreva um código",
        "mostre o código",
        "me dê o código",
        "me de o codigo",
        "como implementar",
        "como implementar isso",
        "como faço essa função",
        "como faço essa function",
        "como criar essa função",
        "como criar essa function",
        "mande o código",
        "manda o código",
    ]

    if any(trigger in text_lower for trigger in explicit_code_triggers):
        return "CODE"

    return None

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
        cleaned_msg = last_msg.replace("@heavy", "").strip()
        state["messages"][-1].content = cleaned_msg
        return {"actual_route": "HEAVY"}

    if explicit_route:
        return {"actual_route": explicit_route}

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

    print(
        f"🔀 [ROUTER RESULTADO] "
        f"Rota final escolhida: '{decision.route}'"
    )

    return {"actual_route": decision.route}


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
    response.name = "Qwen3 Coder (30B)"
    
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
        return "code_response"
    elif destiny == "HEAVY":
        return "heavy_task_response"
    elif destiny == "NOTES":
        return "note_response"
    else:
        return "standard_response"

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
    


def build_graph():
    builder = StateGraph(State)

    builder.add_node("router_node", router_node)
    
    builder.add_node("standard_node_20b", standard_node_20b)
    builder.add_node("code_node", code_node)
    builder.add_node("note_node", note_node)
    builder.add_node("heavy_task_node_70b", heavy_task_node_70b)
    builder.add_node("summarize_node", summarize_node)
    
    
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
            "standard_response": "standard_node_20b",
            "code_response": "code_node",
            "note_response": "note_node",
            "heavy_task_response": "heavy_task_node_70b",
        }
    )


    builder.add_edge("standard_node_20b", END)
    builder.add_edge("code_node", END)
    builder.add_edge("note_node", END)
    builder.add_edge("heavy_task_node_70b", END)

    return builder


def compile_graph():
    return build_graph().compile()
    