"""Resumo de passagem de bastão entre chats (chat cheio -> chat novo).

O resumo gerado na troca de chat fica no campo `summary` do estado, dentro de um bloco marcado.
O `summarize_node` (que reescreve o resumo a cada ~10 mensagens, em um parágrafo) preserva esse bloco
em vez de comprimi-lo, para o chat novo não esquecer o que veio do anterior.
"""

import re

HANDOFF_BEGIN = "[[CONTINUAÇÃO DO CHAT ANTERIOR]]"
HANDOFF_END = "[[FIM DA CONTINUAÇÃO]]"


def split_handoff(summary: str | None) -> tuple[str, str]:
    """Separa o resumo em (bloco de continuação, resto). Sem bloco válido: ("", resumo inteiro)."""
    text = summary or ""
    start = text.find(HANDOFF_BEGIN)
    if start < 0:
        return "", text.strip()
    end = text.find(HANDOFF_END, start)
    if end < 0:
        return "", text.strip()
    handoff = text[start + len(HANDOFF_BEGIN):end].strip()
    rest = (text[:start] + text[end + len(HANDOFF_END):]).strip()
    return handoff, rest


def join_handoff(handoff: str | None, current: str | None) -> str:
    """Inverso de split_handoff: bloco de continuação (se houver) + resumo corrente."""
    handoff = (handoff or "").strip()
    current = (current or "").strip()
    if not handoff:
        return current
    block = f"{HANDOFF_BEGIN}\n{handoff}\n{HANDOFF_END}"
    return f"{block}\n\n{current}" if current else block


def plain_summary(summary: str | None) -> str:
    """Resumo inteiro sem os marcadores (para alimentar o LLM que fará o próximo resumo)."""
    handoff, rest = split_handoff(summary)
    return "\n\n".join(part for part in (handoff, rest) if part)


# ----------------------------------------------------------------------
# Resumo corrente da conversa (usado pelo summarize_node)
# ----------------------------------------------------------------------

WRITE_TOOLS = (
    "create_new_file", "edit_existing_file", "batch_edit_file", "append_to_file",
    "replace_in_file", "write_markdown_file", "create_pdf_file",
)

SUMMARY_PROMPT = (
    "Você mantém o RESUMO CORRENTE de uma conversa entre um usuário e um assistente de programação. "
    "Atualize o resumo com as mensagens novas: mantenha o que continua válido, remova o que ficou obsoleto e "
    "acrescente o que é novo. Escreva em português, em tópicos curtos, no máximo 180 palavras, com as seções:\n"
    "- Objetivo\n- Feito e decidido (cite nomes de arquivos, funções e valores)\n- Pendências\n"
    "- Preferências do usuário\n"
    "Não invente nada, não copie código. Responda apenas com o resumo atualizado."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def strip_think(text: str | None) -> str:
    return _THINK_RE.sub("", text or "").strip()


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
            if isinstance(block, (str, dict))
        )
    return str(content or "")


def summary_transcript(messages, limit: int = 10, per_message: int = 1500, total: int = 14000) -> str:
    """Últimas mensagens de CONVERSA (sem tools e sem avisos internos), cada uma cortada, como texto único."""
    pairs: list[tuple[str, str]] = []
    for m in messages:
        kind = getattr(m, "type", "")
        if kind not in ("human", "ai") or (kind == "ai" and getattr(m, "tool_calls", None)):
            continue
        tag = str((getattr(m, "additional_kwargs", None) or {}).get("message_tag") or "")
        if tag.startswith("internal_") or tag.startswith("chat_handoff"):
            continue
        text = text_of(getattr(m, "content", "")).strip()
        if text:
            pairs.append(("Usuário" if kind == "human" else "Assistente", text))
    chunks = [
        f"[{role}] {text if len(text) <= per_message else text[: per_message - 1].rstrip() + '…'}"
        for role, text in pairs[-limit:]
    ]
    kept: list[str] = []
    used = 0
    for chunk in reversed(chunks):  # prioriza o mais recente
        if kept and used + len(chunk) > total:
            break
        kept.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(reversed(kept))


def edited_files(messages, limit: int = 15) -> list[str]:
    """Arquivos que o agente tentou editar/criar (pelas chamadas de ferramenta), do mais antigo ao mais recente."""
    seen: dict[str, bool] = {}
    for m in messages:
        for call in getattr(m, "tool_calls", None) or []:
            if call.get("name") in WRITE_TOOLS:
                path = (call.get("args") or {}).get("file_path")
                if path:
                    seen.pop(path, None)
                    seen[path] = True
    return list(seen)[-limit:]
