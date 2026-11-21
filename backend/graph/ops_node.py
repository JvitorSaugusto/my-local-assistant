"""Nó do chat para git e pacotes de contexto: pergunta, lê as mudanças reais e só então age."""
from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from . import ops_core as core
from . import ops_groups
from .ops_core import OPS_NAME, parse_delivery

MAX_ROUNDS = 12
MAX_HISTORY = 8

COMMIT_TOOLS = {"git_commit_groups", "git_commit_files"}
ZIP_TOOL = "build_zip_files"
TXT_TOOL = "build_txt_files"
DELIVERY_OK = ("Zip pronto", "TXT pronto")
_TXT_LINK = re.compile(r"/api/handoff/packs/arquivos_[\w.-]+\.txt")
_CLAIMS_TXT = re.compile(r"\btxt\s+(?:pronto|criado|gerado|montado)", re.I)
_ZIP_LINK = re.compile(r"/api/handoff/zips/[\w.-]+\.zip")
_CLAIMS_ZIP = re.compile(r"\bzip\s+(?:pronto|criado|gerado|montado)", re.I)
NO_ZIP_MADE = "Não consegui gerar o zip desta vez. Peça de novo dizendo os nomes dos arquivos ou da pasta."
ZIP_RETRY = (
    "SISTEMA: você disse que gerou um arquivo (zip ou txt), mas a ferramenta de entrega não rodou. "
    "Chame build_zip_files (zip) ou build_txt_files (txt) com os nomes pedidos. Não escreva links; o sistema mostra o resultado real."
)


def _invented_zip_report(text, outputs):
    """True se o texto cita link ou diz que gerou um zip sem a ferramenta ter produzido isso."""
    known = "\n".join(outputs)
    links = _ZIP_LINK.findall(text) + _TXT_LINK.findall(text)
    if any(link not in known for link in links):
        return True
    claims = bool(_CLAIMS_ZIP.search(text)) or bool(_CLAIMS_TXT.search(text))
    return claims and not any(ok in known for ok in DELIVERY_OK)


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
2. Para cada grupo escolhido chame git_diff_files e escreva a mensagem a partir do diff REAL seguindo Conventional Commits: 'tipo: resumo' ou 'tipo(escopo): resumo' (tipos: feat, fix, refactor, docs, test, chore, style, perf, build, ci), no imperativo em português, até 72 caracteres. Você pode juntar grupos do mesmo assunto ou dividir um grupo, mas NUNCA faça um commit único com assuntos misturados nem com mais de 8 arquivos, mesmo se o usuário disser 'todos': 'todos' significa todos os grupos, cada um no seu commit.
3. Chame git_commit_groups UMA vez com todos os grupos (lista de {paths, message}). Informe cada hash, os arquivos e como desfazer. Use git_commit_files só para um commit avulso.
Quando o usuário responder 'todos', números de grupo ou nomes de arquivo, chame git_group_overview DE NOVO (a lista muda a cada commit; os números valem para a lista mais recente) e só então prossiga.
Só as ferramentas git_commit_groups e git_commit_files commitam, e o resultado delas é enviado direto ao usuário. NUNCA escreva hashes, nunca diga que commitou e nunca liste commits sem ter chamado uma delas.
Nunca invente arquivos: só os que as ferramentas listaram. Nunca commite segredos. Se estiver em main/master, avise e pare.

PACOTE .md PARA OUTRA IA (o usuário quer mandar um problema para o Claude ou outra IA):
1. Se faltar o problema, pergunte em uma frase.
2. Se ele citou arquivos, use-os. Senão chame suggest_files_for_problem e mostre até 6 opções numeradas com o motivo curto; pergunte quais incluir ou se ele prefere dizer os nomes.
3. Chame build_context_pack com o problema (uma frase mais os detalhes que ele deu) e os arquivos. Responda com o link EXATAMENTE como a ferramenta devolveu, os tokens e o que ficou de fora.
Pedido só do resumo do projeto/primer: chame build_primer_file.

ZIP DE ARQUIVOS (o usuário quer receber arquivos ou pastas do projeto no chat, ex.: 'me entregue os arquivos x, y, z'):
1. Chame build_zip_files UMA vez com os nomes exatamente como o usuário escreveu: nome simples (script.js), caminho parcial, caminho completo ou nome de pasta (rag). Pastas inteiras e arquivos de pastas diferentes podem ir juntos no mesmo zip.
2. Se a ferramenta devolver ERRO de nome ambíguo ou não encontrado, pergunte ao usuário o caminho completo (uma pergunta só). Nunca adivinhe e nunca troque por outro arquivo.
3. O resultado com o link é enviado direto ao usuário. NUNCA escreva links de download nem diga que o zip está pronto sem ter chamado a ferramenta. Segredos (.env, chaves) ficam sempre de fora.

TXT DE ARQUIVOS (o usuário pede 'em txt', '@txt', 'gera um txt' com arquivos do projeto):
1. Chame build_txt_files UMA vez com os nomes como o usuário escreveu e with_map=true somente se ele pediu o mapa do projeto (ex.: 'com o mapa', 'inclua o mapa').
2. Mesmas regras do ZIP: ERRO de nome ambíguo ou não encontrado, pergunte o caminho completo; nunca escreva links nem diga que o txt está pronto sem chamar a ferramenta. Arquivos inexistentes são listados pela própria ferramenta.
3. Pedido de entregar arquivos NUNCA se resolve com git_changes_overview nem git_group_overview: use build_zip_files (ou build_txt_files se pediu txt).

Se o pedido não for sobre git, pacote, zip nem txt, diga isso em uma frase."""


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


async def _direct_delivery(history, by_name):
    """Pedido claro de zip/txt (com nomes): roda a ferramenta direto, sem LLM, e devolve o resultado real (link ou ERRO)."""
    last = next((m for m in reversed(history) if getattr(m, "type", "") == "human"), None)
    if last is None:
        return None
    request = parse_delivery(_text(last.content))
    if request is None:
        return None
    kind, names, with_map = request
    if not names and not (kind == "txt" and with_map):
        return None
    if kind == "txt":
        tool, args = by_name.get("build_txt_files"), {"names": names, "with_map": with_map}
    else:
        tool, args = by_name.get("build_zip_files"), {"names": names}
    if tool is None:
        return None
    try:
        output = str(await tool.ainvoke(args))
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"
    return output.replace("Peça ao usuário o caminho completo.", "Diga o caminho completo do arquivo.")


_GENERIC_COMMIT_REQ = re.compile(
    r"^\s*(?:@?(?:commit|ops)\b[:\s]*)?(?:por\s+favor[,\s]+)?"
    r"(?:(?:pode|poderia|consegue)\s+)?"
    r"(?:(?:quero|preciso)\s+(?:de\s+)?)?"
    r"(?:(?:fa[çc]a|faz(?:er)?|d[êe])\s+(?:os?\s+|uns?\s+|um\s+)?)?"
    r"(?:commits?|commita[r]?|commite|comita[r]?|comite)"
    r"(?:\s+(?:os\s+|meus\s+|as\s+|minhas\s+)?(?:arquivos?|altera[çc][õo]es|mudan[çc]as|grupos?|tudo|todos))?"
    r"(?:\s+por\s+favor)?\s*[.!?]*\s*$",
    re.I,
)
_COMMIT_CHOICE_PROMPT = re.compile(
    r"qua(?:l\(is\)|is)\s+(?:grupos?|arquivos?)|responda\s+com\b.*\btodos\b|deseja\s+commitar",
    re.I,
)
_COMMIT_MORE_PROMPT = re.compile(r"deseja\s+commitar\s+mais\s+alguma\s+coisa", re.I)
_COMMIT_CANCEL = re.compile(r"^\s*(?:n[ãa]o|nenhum|cancela\w*|deixa|para\w*)\s*[.!?]*\s*$", re.I)
_COMMIT_ALL = re.compile(
    r"^\s*(?:todos|todas|tudo|sim|ok|pode|manda|commita\s+tudo|todos\s+os\s+grupos)\s*[.!?]*\s*$",
    re.I,
)
_COMMIT_NUMS = re.compile(r"^\s*(?:grupos?\s*)?\d+(?:\s*(?:,|e|\s)\s*\d+)*\s*[.!?]*\s*$", re.I)
_CONVENTIONAL_PREFIX = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|style|perf|build|ci)(\([a-z0-9._/-]+\))?:\s+\S",
    re.I,
)

_COMMIT_MSG_PROMPT = (
    "Você gera mensagens de commit no padrão Conventional Commits a partir de diffs reais do git.\n"
    "Responda SOMENTE com um array JSON válido no formato:\n"
    '[{"group": 1, "message": "tipo(escopo): resumo curto no imperativo em português"}]\n'
    "Regras:\n"
    "- Use apenas os tipos: feat, fix, refactor, docs, test, chore, style, perf, build ou ci.\n"
    "- Escopo entre parênteses é opcional e curto (ex.: feat(ops): ... ou fix: ...).\n"
    "- Primeira linha em português, no imperativo, até 72 caracteres, sem ponto final.\n"
    "- Baseie cada mensagem APENAS no diff fornecido para aquele grupo.\n"
    "- Nenhum texto fora do JSON."
)


def _prev_ai_text(history) -> str:
    last_human_idx = next(
        (i for i in range(len(history) - 1, -1, -1) if getattr(history[i], "type", "") == "human"),
        None,
    )
    if last_human_idx is None:
        return ""
    for msg in reversed(history[:last_human_idx]):
        if getattr(msg, "type", "") == "ai":
            return _text(msg.content)
    return ""


def _format_commit_overview(workspace: str) -> str:
    if not core.is_repo(workspace):
        return "ERRO: não é um repositório git."
    branch = core.current_branch(workspace)
    if branch in core.PROTECTED_BRANCHES:
        return f"Você está na branch protegida '{branch}'. Troque para uma branch de trabalho antes de commitar."
    groups, skipped = ops_groups.group_changes(core.git_changes(workspace))
    overview = ops_groups.format_groups(groups, skipped, branch)
    if not groups:
        return overview
    return (
        f"{overview}\n\n"
        "Quais grupos ou arquivos você quer commitar? "
        "Responda com **todos**, números dos grupos (ex.: `1 2`), nomes de arquivo ou **cancelar**."
    )


def _fallback_commit_message(group: dict) -> str:
    label = str(group.get("label") or "").strip()
    paths = list(group.get("paths") or [])
    items = list(group.get("items") or [])
    if label == "docs" or (paths and all(p.lower().endswith(".md") for p in paths)):
        return "docs: atualizar documentação"
    if paths and all("test" in p.lower() for p in paths):
        return "test: atualizar testes"
    all_new = bool(items) and all(i.get("status") == "novo" for i in items)
    kind = "feat" if all_new else "chore"
    scope = re.sub(r"[^a-z0-9._/-]+", "-", label.split("/")[-1].lower()).strip("-")[:20]
    prefix = f"{kind}({scope})" if scope and scope != "(raiz)" else kind
    action = "adicionar" if all_new else "atualizar"
    target = paths[0].rsplit("/", 1)[-1] if len(paths) == 1 else f"{len(paths)} arquivos"
    return f"{prefix}: {action} {target}"[:72]


def _parse_commit_messages(raw: str, group_numbers: list[int]) -> dict[int, str]:
    parsed: dict[int, str] = {}
    text = raw or ""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL | re.I)
    bracket = re.search(r"\[.*\]", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else (bracket.group(0) if bracket else "")
    if not candidate:
        return parsed
    try:
        data = json.loads(candidate)
    except ValueError:
        return parsed
    if not isinstance(data, list):
        return parsed
    for pos, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        msg = str(item.get("message") or "").strip().splitlines()[0].strip() if item.get("message") else ""
        if not msg:
            continue
        raw_num = item.get("group")
        if isinstance(raw_num, int) or (isinstance(raw_num, str) and raw_num.isdigit()):
            num = int(raw_num)
        elif pos < len(group_numbers):
            num = group_numbers[pos]
        else:
            num = None
        if num in group_numbers:
            parsed[num] = msg[:72]
    return parsed


async def _build_commit_messages(workspace: str, numbered_groups: list[tuple[int, dict]], llm=None) -> list[dict]:
    sections = []
    for num, group in numbered_groups:
        diff = core.diff_text(workspace, group["paths"], per_file=2000, total=5000)
        sections.append(
            f"=== GRUPO {num} ({group['label']}) ===\n"
            f"Arquivos: {', '.join(group['paths'])}\n"
            f"{diff}"
        )
    prompt = "\n\n".join(sections)[:24000]
    model = llm
    if model is None:
        from .config import generate_llm

        model = generate_llm
    messages_by_num: dict[int, str] = {}
    try:
        reply = await model.ainvoke([SystemMessage(content=_COMMIT_MSG_PROMPT), HumanMessage(content=prompt)])
        messages_by_num = _parse_commit_messages(_text(reply.content), [num for num, _ in numbered_groups])
    except Exception:  # noqa: BLE001
        messages_by_num = {}

    plan = []
    for num, group in numbered_groups:
        msg = messages_by_num.get(num, "").strip()
        if not msg or not _CONVENTIONAL_PREFIX.match(msg):
            msg = _fallback_commit_message(group)
        plan.append({"paths": group["paths"], "message": msg})
    return plan


async def _direct_commit(history, workspace: str, llm=None) -> str | None:
    """Fluxo determinístico para listar grupos e commitar seleção (evita loop e perda de lista no LLM)."""
    last = next((m for m in reversed(history) if getattr(m, "type", "") == "human"), None)
    if last is None:
        return None
    text = _text(last.content).strip()
    if not text:
        return None

    if _GENERIC_COMMIT_REQ.match(text):
        return _format_commit_overview(workspace)

    prev_ai = _prev_ai_text(history)
    if not prev_ai or not _COMMIT_CHOICE_PROMPT.search(prev_ai):
        return None

    if _COMMIT_CANCEL.match(text):
        return "Ok, nenhum commit foi feito."

    if _COMMIT_MORE_PROMPT.search(prev_ai) and re.fullmatch(r"\s*(?:sim|ok|pode|quero)\s*[.!?]*\s*", text, re.I):
        return _format_commit_overview(workspace)

    is_all = bool(_COMMIT_ALL.match(text))
    is_nums = bool(_COMMIT_NUMS.match(text))
    if not is_all and not is_nums:
        return None

    if not core.is_repo(workspace):
        return "ERRO: não é um repositório git."
    branch = core.current_branch(workspace)
    if branch in core.PROTECTED_BRANCHES:
        return f"Você está na branch protegida '{branch}'. Troque para uma branch de trabalho antes de commitar."

    groups, skipped = ops_groups.group_changes(core.git_changes(workspace))
    if not groups:
        return ops_groups.format_groups(groups, skipped, branch)

    if is_all:
        chosen = [(idx, grp) for idx, grp in enumerate(groups, 1)]
    else:
        nums = list(dict.fromkeys(int(n) for n in re.findall(r"\d+", text)))
        invalid = [n for n in nums if n < 1 or n > len(groups)]
        if invalid:
            overview = ops_groups.format_groups(groups, skipped, branch)
            return f"Grupo(s) inválido(s): {', '.join(map(str, invalid))}.\n\n{overview}"
        chosen = [(n, groups[n - 1]) for n in nums]

    plan = await _build_commit_messages(workspace, chosen, llm=llm)
    report = ops_groups.commit_groups(workspace, plan)
    if "Ficaram sem commit" in report:
        report += "\n\nDeseja commitar mais alguma coisa?"
    return report


async def run_ops(history, workspace, thread_id=None, llm=None, max_rounds=MAX_ROUNDS, direct_commit=None):
    """Loop próprio de ferramentas. Devolve o texto final da resposta."""
    from . import ops_tools as tools_module

    if not (workspace or "").strip():
        return "Selecione um diretório de trabalho para eu olhar o git e montar pacotes."
    tools_module.set_context(workspace, thread_id)
    by_name = {t.name: t for t in tools_module.OPS_TOOLS}
    direct = await _direct_delivery(history, by_name)
    if direct is not None:
        return direct
    use_direct_commit = (llm is None) if direct_commit is None else direct_commit
    if use_direct_commit:
        committed = await _direct_commit(history, workspace, llm=llm)
        if committed is not None:
            return committed
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
            if _invented_zip_report(text, outputs):
                if warned:
                    return NO_ZIP_MADE
                warned = True
                messages.append(reply)
                messages.append(HumanMessage(content=ZIP_RETRY))
                continue
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
        zip_outputs = []
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
            elif call["name"] in (ZIP_TOOL, TXT_TOOL) and output.startswith(DELIVERY_OK):
                zip_outputs.append(output)
            messages.append(ToolMessage(content=output[:12000], tool_call_id=call.get("id") or call["name"], name=call["name"]))
        if zip_outputs and not commit_outputs:
            return "\n\n".join(zip_outputs)
        if commit_outputs:
            # Resposta final = o que o git realmente fez, sem passar pelo modelo.
            report = "\n\n".join(commit_outputs)
            if "Ficaram sem commit" in report:
                report += "\n\nDeseja commitar mais alguma coisa?"
            return report
    return "Não consegui concluir em poucos passos. Diga quais arquivos você quer e eu continuo."


async def _record_artifacts_from_text(thread_id: str | None, text: str) -> None:
    if not thread_id or not text:
        return
    matches = _TXT_LINK.findall(text) + re.findall(r"/api/handoff/packs/[\w.-]+\.md", text)
    if not matches:
        return
    try:
        from pathlib import Path
        from backend.graph.ops_core import pack_file_path
        from backend.handoff.artifacts import record_artifact

        for link in dict.fromkeys(matches):
            fname = link.rsplit("/", 1)[-1]
            p = pack_file_path(fname)
            size = p.stat().st_size if p else 0
            await record_artifact(thread_id, fname, Path(fname).suffix.lstrip(".").lower(), fname, size)
    except Exception:  # noqa: BLE001
        pass


async def ops_node(state, config=None):
    from .node_helpers import now_iso

    configurable = (config or {}).get("configurable") or {}
    thread_id = state.get("thread_id") or configurable.get("thread_id")
    history = build_history(state.get("messages"))
    text = await run_ops(history, state.get("workspace_path") or "", thread_id)
    await _record_artifacts_from_text(thread_id, text)
    reply = AIMessage(
        content=text,
        name=OPS_NAME,
        additional_kwargs={"message_tag": "response_ops", "created_at": now_iso()},
    )
    return {"messages": [reply], "active_node": "ops_node", "enhanced_prompt": None}