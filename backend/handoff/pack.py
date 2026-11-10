"""Pacote para IA externa (Fase B): UM .md dentro de um orçamento de tokens.

Você descreve o problema; o sistema reaproveita o RAG e o dossiê (`build_task_dossier`), junta o primer,
mascara segredos e declara o que ficou de fora, para a IA externa pedir PELO NOME em vez de você
reenviar arquivos inteiros.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .masking import mask_secrets
from .primer import build_primer, estimate_tokens

DEFAULT_BUDGET = 25_000
_MAX_AUTO_FILES = 4
_OMITTED_LINES = 25


async def _rag_hits(workspace: str, problem: str, limit: int = 14) -> tuple[list, str]:
    """(hits, aviso). O RAG é opcional: se faltar, o pacote sai só com o que foi pedido."""
    try:
        from backend.rag import get_service

        service = get_service()
        await service.refresh_workspace(workspace)  # só o que mudou; com trava de intervalo
        hits, _label, sources = await service.search_scoped(problem, workspace, None, limit, None)
        if not sources:
            return [], "RAG sem fonte indexada para este projeto: indique os arquivos em `files` ou indexe em /static/rag.html."
        return hits, ""
    except Exception as exc:  # noqa: BLE001
        return [], f"RAG indisponível ({exc}); pacote montado sem busca semântica."


def _clean_files(workspace: str, files: list[str] | None) -> list[str]:
    root = Path(workspace).resolve()
    out: list[str] = []
    for item in files or []:
        rel = str(item).strip().replace("\\", "/")
        if not rel or rel in out:
            continue
        try:
            (root / rel).resolve().relative_to(root)  # nada fora do projeto
        except ValueError:
            continue
        out.append(rel)
    return out


def _dossier_body(text: str) -> str:
    """Troca a instrução endereçada ao agente local por um título neutro para a IA externa."""
    _head, _sep, rest = text.partition("\n\n")
    return "## Arquivos e alterações recentes\n" + rest if rest else text


async def build_pack(
    workspace: str,
    problem: str,
    files: list[str] | None = None,
    budget_tokens: int = DEFAULT_BUDGET,
    instructions: str | None = None,
    thread_id: str | None = None,
) -> dict:
    problem = (problem or "").strip()
    if not problem:
        raise ValueError("Descreva o problema.")
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Pasta não encontrada: {workspace}")
    budget_tokens = max(4_000, min(int(budget_tokens), 120_000))
    budget_chars = budget_tokens * 3

    from backend.graph.context_builder import build_task_dossier  # import tardio: só quando o pacote é pedido

    primer = (await build_primer(str(root), 2000, thread_id))["markdown"]
    hits, warning = await _rag_hits(str(root), problem)

    chosen = _clean_files(str(root), files)
    auto = not chosen
    if auto:
        for hit in hits:
            if hit.path not in chosen:
                chosen.append(hit.path)
            if len(chosen) >= _MAX_AUTO_FILES:
                break

    fixed = [
        "# PACOTE DE CONTEXTO PARA IA EXTERNA",
        f"## Problema\n{problem}",
    ]
    if instructions and instructions.strip():
        fixed.append(f"## Instruções\n{instructions.strip()}")
    fixed.append(
        "## Como usar este pacote\n"
        "Os trechos abaixo vêm do repositório real (linhas numeradas). Se faltar algo, peça pelo NOME "
        "(arquivo + função ou linhas) usando a seção 'Fora do pacote'. Não invente conteúdo que não "
        "aparece aqui; escreva VERIFICAR."
    )
    fixed.append(primer)
    fixed_chars = sum(len(p) for p in fixed) + 400

    dossier_chars = max(6_000, int((budget_chars - fixed_chars) * 0.65))
    dossier_text, report = "", {"files": [], "truncated": False}
    shown_extra: list = []
    extra_text = ""

    for _attempt in range(4):
        if chosen:
            dossier_text, report = await asyncio.to_thread(
                build_task_dossier, str(root), chosen, dossier_chars, min(20_000, dossier_chars // 2), 12_000
            )
        in_dossier = {e["path"] for e in report.get("files", []) if e.get("mode") in {"completo", "parcial"}}
        rag_budget = max(0, budget_chars - fixed_chars - len(dossier_text) - 3_000)
        extra = [h for h in hits if h.path not in in_dossier]
        shown_extra, extra_text = [], ""
        if extra and rag_budget > 1_500:
            from backend.rag.search import format_hits

            shown_extra = extra[:5]
            extra_text = format_hits(shown_extra, max_chars=rag_budget, snippet_chars=1_000)
        body_len = fixed_chars + len(dossier_text) + len(extra_text) + 3_000
        if body_len <= budget_chars:
            break
        dossier_chars = int(dossier_chars * 0.7)  # estourou: reduz o dossiê e refaz
    # lista do que ficou de fora (barata: uma linha por trecho)
    in_dossier = {e["path"] for e in report.get("files", []) if e.get("mode") in {"completo", "parcial"}}
    shown_ids = {id(h) for h in shown_extra}
    omitted: list[str] = []
    for entry in report.get("files", []):
        if entry.get("mode") == "parcial":
            omitted.append(f"{entry['path']} — enviado PARCIAL ({entry['lines']} linhas); peça outras partes por função/linhas")
        elif entry.get("mode") not in {"completo", "parcial"}:
            omitted.append(f"{entry['path']} — {entry.get('mode')}")
    for hit in hits:
        if hit.path in in_dossier or id(hit) in shown_ids:
            continue
        omitted.append(f"{hit.path}:{hit.start_line}-{hit.end_line} {hit.qualname} — {hit.summary or '-'}")
    omitted = omitted[:_OMITTED_LINES]

    sections = list(fixed)
    if dossier_text:
        sections.append(_dossier_body(dossier_text))
    if extra_text:
        sections.append("## Trechos relacionados (RAG)\n" + extra_text)
    if warning:
        sections.append(f"## Aviso\n{warning}")
    sections.append(
        "## Fora do pacote (peça pelo nome)\n" + ("\n".join(f"- {line}" for line in omitted) if omitted else "- (nada relevante ficou de fora)")
    )

    markdown, masked = mask_secrets("\n\n".join(sections))
    return {
        "markdown": markdown,
        "est_tokens": estimate_tokens(markdown),
        "budget_tokens": budget_tokens,
        "masked": masked,
        "files": [e["path"] for e in report.get("files", []) if e.get("mode") in {"completo", "parcial"}],
        "omitted": omitted,
        "auto_files": auto,
        "warning": warning,
    }
