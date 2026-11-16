"""Resumo de passagem de bastão entre chats (chat cheio -> chat novo).

O resumo gerado na troca de chat fica no campo `summary` do estado, dentro de um bloco marcado.
O `summarize_node` (que reescreve o resumo a cada ~10 mensagens, em um parágrafo) preserva esse bloco
em vez de comprimi-lo, para o chat novo não esquecer o que veio do anterior.
"""

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
