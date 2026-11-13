"""Nó do chat para git e pacotes de contexto: pergunta, lê as mudanças reais e só então age."""
from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .ops_core import OPS_NAME

MAX_ROUNDS = 12
MAX_HISTORY = 8

COMMIT_TOOLS = {"git_commit_groups", "git_commit_files"}
# hash curto/longo do git (precisa ter pelo menos um dígito, para não confundir com palavras como "defaced")
_HASH = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
_CLAIMS_COMMIT = re.compile(r"commits?\s+(?:realizados?|feitos?|criados?|conclu[ií]dos?)", re.I)
NO_COMMIT_MADE = (
    "Nenhum commit foi feito: eu não consegui executar a ferramenta de commit desta vez. "
    "Responda 'todos' (ou os números dos grupos) de novo para eu tentar outra vez. "
    "Confira com `git log --oneline -5`."
)


def _invented_commit_report(text, outputs):
    """True se o texto diz que commitou (ou cita hashes) sem que nenhuma ferramenta tenha produzido isso."""
    known = "\n".join(outputs)
    if any(h not in known for h in _HASH.findall(text)):
        return True
    return bool(_CLAIMS_COMMIT.search(text))

OPS_SYSTEM_PROMPT = """Você é o assistente de git e de pacotes de contexto deste projeto. Responda em português, curto, uma pergunta por vez.

COMMIT (o usuário quer commitar arquivos que ele mesmo alterou):
1. Chame git_group_overview: ele já agrupa os arquivos por assunto (testes junto do código, docs separados). Mostre os grupos numerados, com os arquivos, e pergunte quais commitar (aceite 'todos', números de grupo ou nomes de arquivo).
2. Para cada grupo escolhido chame git_diff_files e escreva a mensagem a partir do diff REAL, no formato 'tipo: resumo' (feat, fix, refactor, docs, test, chore), até 72 caracteres. Você pode juntar grupos do mesmo assunto ou dividir um grupo, mas NUNCA faça um commit único com assuntos misturados nem com mais de 8 arquivos, mesmo se o usuário disser 'todos': 'todos' significa todos os grupos, cada um no seu commit.
3. Chame git_commit_groups UMA vez com todos os grupos (lista de {paths, message}). Informe cada hash, os arquivos e como desfazer. Use git_commit_files só para um commit avulso.
Quando o usuário responder 'todos', números de grupo ou nomes de arquivo, chame git_group_overview DE NOVO (a lista muda a cada commit; os números valem para a lista mais recente) e só então prossiga.
Só as ferramentas git_commit_groups e git_commit_files commitam, e o resultado delas é enviado direto ao usuário. NUNCA escreva hashes, nunca diga que commitou e nunca liste commits sem ter chamado uma delas.
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
    outputs = []  # tudo o que as ferramentas devolveram nesta execução
    warned = False
    for _round in range(max_rounds):
        reply = await llm.ainvoke(messages)
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            text = _text(reply.content).strip()
            if not text:
                return "Não consegui responder. Reformule o pedido."
            # O modelo não pode relatar commits que nenhuma ferramenta fez (antes ele inventava hashes e arquivos).
            if _invented_commit_report(text, outputs):
                if warned:
                    return NO_COMMIT_MADE
                warned = True
                messages.append(reply)
                messages.append(
                    HumanMessage(
                        content=(
                            "SISTEMA: você disse que commitou, mas nenhuma ferramenta de commit rodou. Nada foi commitado. "
                            "Chame git_group_overview e depois git_commit_groups (ou git_commit_files). "
                            "Não escreva hashes nem relatório de commits; o sistema mostra o resultado real."
                        )
                    )
                )
                continue
            return text
        messages.append(reply)
        commit_outputs = []
        for call in calls:
            tool = by_name.get(call["name"])
            try:
                output = await tool.ainvoke(call.get("args") or {}) if tool else f"ERRO: ferramenta desconhecida '{call['name']}'."
            except Exception as exc:  # noqa: BLE001
                output = f"ERRO: {exc}"
            output = str(output)
            outputs.append(output)
            if call["name"] in COMMIT_TOOLS:
                commit_outputs.append(output)
            messages.append(ToolMessage(content=output[:12000], tool_call_id=call.get("id") or call["name"], name=call["name"]))
        if commit_outputs:
            # Resposta final = o que o git realmente fez, sem passar pelo modelo.
            report = "\n\n".join(commit_outputs)
            if "Ficaram sem commit" in report:
                report += "\n\nDeseja commitar mais alguma coisa?"
            return report
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