"""Nó do chat para git e pacotes de contexto: pergunta, lê as mudanças reais e só então age."""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .ops_core import OPS_NAME

MAX_ROUNDS = 12
MAX_HISTORY = 8

OPS_SYSTEM_PROMPT = """Você é o assistente de git e de pacotes de contexto deste projeto. Responda em português, curto, uma pergunta por vez.

COMMIT (o usuário quer commitar arquivos que ele mesmo alterou):
1. Chame git_group_overview: ele já agrupa os arquivos por assunto (testes junto do código, docs separados). Mostre os grupos numerados, com os arquivos, e pergunte quais commitar (aceite 'todos', números de grupo ou nomes de arquivo).
2. Para cada grupo escolhido chame git_diff_files e escreva a mensagem a partir do diff REAL, no formato 'tipo: resumo' (feat, fix, refactor, docs, test, chore), até 72 caracteres. Você pode juntar grupos do mesmo assunto ou dividir um grupo, mas NUNCA faça um commit único com assuntos misturados nem com mais de 8 arquivos, mesmo se o usuário disser 'todos': 'todos' significa todos os grupos, cada um no seu commit.
3. Chame git_commit_groups UMA vez com todos os grupos (lista de {paths, message}). Informe cada hash, os arquivos e como desfazer. Use git_commit_files só para um commit avulso.
Nunca invente arquivos: só os que as ferramentas listaram. Nunca commite segredos. Se estiver em main/master, avise e pare.

PACOTE .md PARA OUTRA IA (o usuário quer mandar um problema para o Claude ou outra IA):
1. Se faltar o problema, pergunte em uma frase.
2. Se ele citou arquivos, use-os. Senão chame suggest_files_for_problem e mostre até 6 opções numeradas com o motivo curto; pergunte quais incluir ou se ele prefere dizer os nomes.
3. Chame build_context_pack com o problema (uma frase mais os detalhes que ele deu) e os arquivos. Responda com o link EXATAMENTE como a ferramenta devolveu, os tokens e o que ficou de fora.
Pedido só do resumo do projeto/primer: chame build_primer_file.

Se o pedido não for sobre git nem pacote, diga isso em uma frase."""


def _text(content):
    if isinstance(content, list):
        return " ".join(str(i.get("text", "")) for i in content if isinstance(i, dict))
    return str(content or "")


def build_history(messages, limit=MAX_HISTORY):
    items = []
    for msg in messages or []:
        kind = getattr(msg, "type", "")
        if kind == "human" and getattr(msg, "name", None) != "hidden_task_prompt":
            items.append(HumanMessage(content=_text(msg.content)))
        elif kind == "ai" and not getattr(msg, "tool_calls", None) and _text(msg.content).strip():
            items.append(AIMessage(content=_text(msg.content)))
    return items[-limit:]


async def run_ops(history, workspace, thread_id=None, llm=None, max_rounds=MAX_ROUNDS):
    """Loop próprio de ferramentas. Devolve o texto final da resposta."""
    from . import ops_tools as tools_module

    if not (workspace or "").strip():
        return "Selecione um diretório de trabalho para eu olhar o git e montar pacotes."
    tools_module.set_context(workspace, thread_id)
    by_name = {t.name: t for t in tools_module.OPS_TOOLS}
    if llm is None:
        from .config import generate_llm

        llm = generate_llm.bind_tools(tools_module.OPS_TOOLS)
    messages = [SystemMessage(content=OPS_SYSTEM_PROMPT), *history]
    for _round in range(max_rounds):
        reply = await llm.ainvoke(messages)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            return _text(reply.content).strip() or "Não consegui responder. Reformule o pedido."
        messages.append(reply)
        for call in calls:
            tool = by_name.get(call["name"])
            try:
                output = await tool.ainvoke(call.get("args") or {}) if tool else f"ERRO: ferramenta desconhecida '{call['name']}'."
            except Exception as exc:  # noqa: BLE001
                output = f"ERRO: {exc}"
            messages.append(ToolMessage(content=str(output)[:12000], tool_call_id=call.get("id") or call["name"], name=call["name"]))
    return "Não consegui concluir em poucos passos. Diga quais arquivos você quer e eu continuo."


async def ops_node(state, config=None):
    from .node_helpers import now_iso

    history = build_history(state.get("messages"))
    text = await run_ops(history, state.get("workspace_path") or "", state.get("thread_id"))
    reply = AIMessage(
        content=text,
        name=OPS_NAME,
        additional_kwargs={"message_tag": "response_ops", "created_at": now_iso()},
    )
    return {"messages": [reply], "active_node": "ops_node", "enhanced_prompt": None}
