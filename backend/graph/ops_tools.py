"""Ferramentas do assistente de git e pacotes do chat (usadas só pelo ops_node)."""
from __future__ import annotations

from contextvars import ContextVar

from langchain_core.tools import tool

from . import ops_core as core
from . import ops_groups

_WORKSPACE: ContextVar[str] = ContextVar("ops_workspace", default="")
_THREAD: ContextVar[str | None] = ContextVar("ops_thread", default=None)


def set_context(workspace, thread_id=None):
    _WORKSPACE.set(workspace or "")
    _THREAD.set(thread_id)


def _root():
    return _WORKSPACE.get()


def _link(path):
    return f"[{path.name}](/api/handoff/packs/{path.name})"


@tool
def git_changes_overview() -> str:
    """Lista os arquivos com alterações NÃO commitadas do projeto (modificados, novos, removidos) com linhas +/-. Use antes de qualquer commit."""
    root = _root()
    if not root:
        return "ERRO: nenhum diretório de trabalho selecionado."
    try:
        return core.format_changes(core.git_changes(root), core.current_branch(root))
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


@tool
def git_diff_files(paths: list[str]) -> str:
    """Mostra o diff real (contra o último commit) dos arquivos escolhidos. Aceita caminho completo ou só o nome do arquivo. Use para escrever a mensagem do commit."""
    try:
        return core.diff_text(_root(), paths)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


@tool
def git_commit_files(paths: list[str], message: str) -> str:
    """Commita SOMENTE os arquivos indicados com a mensagem dada (formato 'tipo: resumo', em português, até 72 caracteres na primeira linha). Recusa main/master e arquivos de segredo."""
    try:
        return core.commit_paths(_root(), paths, message)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


@tool
async def suggest_files_for_problem(problem: str) -> str:
    """Sugere os arquivos mais prováveis de estarem ligados a um problema (nome, trechos, alterações recentes e busca semântica). Use antes de montar um pacote .md."""
    root = _root()
    if not root:
        return "ERRO: nenhum diretório de trabalho selecionado."
    extra = []
    try:
        from backend.handoff.pack import _rag_hits

        hits, _warning = await _rag_hits(root, problem, 10)
        extra = [h.path for h in hits]
    except Exception:  # noqa: BLE001 - o RAG é opcional
        extra = []
    ranked = core.suggest_files(root, problem, extra)
    if not ranked:
        return "Não achei candidatos. Peça ao usuário para citar os arquivos."
    return "\n".join(f"{n}. {path} — {reason}" for n, (path, reason) in enumerate(ranked, 1))


@tool
async def build_context_pack(problem: str, files: list[str], instructions: str = "") -> str:
    """Monta UM arquivo .md (problema + resumo do projeto + trechos reais dos arquivos, com segredos mascarados) para enviar a outra IA, e devolve o link para baixar."""
    root = _root()
    if not root:
        return "ERRO: nenhum diretório de trabalho selecionado."
    found, ambiguous, missing = core.resolve_project_files(root, files or [])
    if ambiguous or missing:
        return core._problems_text(ambiguous, missing)
    try:
        from backend.handoff.pack import DEFAULT_BUDGET, build_pack

        result = await build_pack(root, problem, found, DEFAULT_BUDGET, instructions or None, _THREAD.get())
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao montar o pacote: {exc}"
    path = core.save_pack(result["markdown"], problem)
    left = "; ".join(result.get("omitted", [])[:4]) or "nada relevante"
    return (
        f"Pacote pronto: {_link(path)} (~{result['est_tokens']} tokens, {len(result['files'])} arquivo(s) no pacote, "
        f"segredos mascarados: {result['masked']}). Ficou de fora: {left}. Copie o link exatamente como está na resposta."
    )


@tool
async def build_primer_file() -> str:
    """Gera o primer (resumo curto do projeto: arquitetura, rotas, tasks recentes), salva em .md e devolve o link."""
    root = _root()
    if not root:
        return "ERRO: nenhum diretório de trabalho selecionado."
    try:
        from backend.handoff.primer import build_primer

        result = await build_primer(root, 2000, _THREAD.get())
    except Exception as exc:  # noqa: BLE001
        return f"ERRO ao gerar o primer: {exc}"
    path = core.save_pack(result["markdown"], "primer")
    return f"Primer pronto: {_link(path)} (~{result['est_tokens']} tokens). Copie o link exatamente como está."


@tool
def git_group_overview() -> str:
    '''Agrupa os arquivos com alterações NÃO commitadas em grupos coerentes (mesma pasta/assunto, testes junto do código, docs à parte). Use primeiro no fluxo de commit.'''
    root = _root()
    if not root:
        return "ERRO: nenhum diretório de trabalho selecionado."
    try:
        groups, skipped = ops_groups.group_changes(core.git_changes(root))
        return ops_groups.format_groups(groups, skipped, core.current_branch(root))
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


@tool
def git_commit_groups(groups: list[dict]) -> str:
    '''Faz VÁRIOS commits de uma vez, um por grupo. Cada item: {"paths": [arquivos], "message": "tipo: resumo"}. Valida tudo antes: se um grupo for inválido, nenhum commit é feito. Recusa main/master e segredos.'''
    try:
        return ops_groups.commit_groups(_root(), groups)
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


OPS_TOOLS = [
    git_changes_overview,
    git_group_overview,
    git_commit_groups,
    git_diff_files,
    git_commit_files,
    suggest_files_for_problem,
    build_context_pack,
    build_primer_file,
]
