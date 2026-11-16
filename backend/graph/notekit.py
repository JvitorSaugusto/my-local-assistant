"""Modo Notas: perfil de profundidade pelo pedido e checagem de qualidade da nota (sem LLM)."""

from __future__ import annotations

import re

_QUICK = ("rápid", "rapid", "resum", "curt", "breve", "cola ", "cheat", "tl;dr", "em poucas", "sucint")
_DEEP = ("complet", "aprofund", "detalhad", "guia", "tutorial", "do zero", "tudo sobre", "a fundo", "passo a passo", "exaustiv")
_CODE_WORDS = ("python", "javascript", "typescript", "java ", "sql", "api", "função", "funcao", "classe", "código", "codigo",
               "fastapi", "django", "flask", "react", "docker", "git", "bash", "linux", "langgraph", "async", "biblioteca", "framework")
_MIN_WORDS = {"quick": 250, "standard": 700, "deep": 1400}
_MIN_SECTIONS = {"quick": 2, "standard": 4, "deep": 6}


def note_profile(request: str) -> dict:
    text = (request or "").lower()
    if any(w in text for w in _DEEP):
        level = "deep"
    elif any(w in text for w in _QUICK):
        level = "quick"
    else:
        level = "standard"
    if level == "quick" and len(text) > 3000:
        level = "standard"  # conteúdo longo colado: vira nota de verdade, não bilhete
    return {"level": level, "min_words": _MIN_WORDS[level], "min_sections": _MIN_SECTIONS[level],
            "wants_code": any(w in text for w in _CODE_WORDS)}


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


def note_problems(note: str, profile: dict, used_web: bool = False) -> list[str]:
    note = (note or "").strip()
    problems: list[str] = []
    words = word_count(note)
    if words < int(profile["min_words"] * 0.7):
        problems.append(f"está curta ({words} palavras; o alvo é pelo menos {profile['min_words']})")
    if not note.startswith("# "):
        problems.append("não começa com um título '# '")
    if len(re.findall(r"^## ", note, re.M)) < profile["min_sections"]:
        problems.append(f"tem poucas seções '##' (mínimo {profile['min_sections']})")
    if profile["level"] != "quick":
        if profile["wants_code"] and "```" not in note:
            problems.append("não tem nenhum exemplo de código em bloco ```")
        if "consulta rápida" not in note.lower():
            problems.append("falta a seção '## ⚡ Consulta rápida' no final")
    if used_web and not re.search(r"^## .*fontes", note, re.M | re.I):
        problems.append("usou pesquisa na web mas falta a seção '## Fontes' com os links consultados")
    if re.search(r"<rascunho|</rascunho|uso interno", note, re.I):
        problems.append("vazou trecho do rascunho/instruções internas")
    return problems


def note_depth_instruction(profile: dict, web_enabled: bool) -> str:
    level = {"quick": "RÁPIDA (objetiva)", "standard": "PADRÃO", "deep": "APROFUNDADA"}[profile["level"]]
    lines = [
        f"PROFUNDIDADE PEDIDA: {level}. Alvo: pelo menos {profile['min_words']} palavras e {profile['min_sections']} seções '##'.",
        "Cubra: o que é, por que existe, como funciona, como usar (com exemplo), quando usar e quando evitar, erros comuns e limitações.",
    ]
    if profile["level"] != "quick":
        lines.append("Termine com '## ⚡ Consulta rápida' (resumo de 5 a 10 linhas ou tabela para consulta).")
    if web_enabled:
        lines.append(
            "Se o assunto for uma biblioteca, ferramenta, versão, API ou algo que muda com o tempo, confirme com web_search/web_fetch "
            "antes de escrever (no máximo 3 pesquisas) e liste os links realmente consultados em '## Fontes'. Nunca invente links."
        )
    return "\n".join(lines)


NOTE_FIX_PROMPT = (
    "A nota abaixo foi gerada, mas a checagem automática achou estes problemas:\n{problems}\n\n"
    "Reescreva a nota COMPLETA corrigindo todos eles. Preserve tudo que já está correto, aprofunde as partes rasas "
    "com explicações e exemplos reais (sem inventar fatos) e mantenha o formato Markdown começando em '# '.\n"
    "{extra}\n"
    "<nota>\n{note}\n</nota>\n\n"
    "Responda somente com a nota final reescrita."
)
