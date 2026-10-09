"""Monta o histórico "limpo" exibido no chat.

- agrupa por turno (mensagem do usuário -> mensagens da IA);
- a última resposta com texto do turno vira a resposta visível;
- o resto (rascunhos, prompt melhorado, chamadas de tool, <think>,
  reasoning_content) vira `thoughts`, que o front mostra recolhido.
"""

import re
from datetime import datetime

HIDDEN_NAMES = {"Qwen3-Coder (Context Gatherer)", "hidden_task_prompt"}
THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and "text" in part
        )
    return str(content or "")


def split_reasoning(text: str) -> tuple[str, str]:
    """Separa blocos <think>...</think> do texto final."""
    parts = [m.strip() for m in THINK_RE.findall(text)]
    answer = THINK_RE.sub("", text)
    # <think> aberto e nunca fechado
    if "<think>" in answer.lower():
        head, _, tail = re.split(r"(?i)(<think>)", answer, maxsplit=1)
        answer = head
        parts.append(tail.strip())
    return answer.strip(), "\n\n".join(p for p in parts if p)


def _tool_lines(msg) -> list[str]:
    lines = []
    for call in getattr(msg, "tool_calls", None) or []:
        args = ", ".join(
            f"{k}={str(v)[:60]!r}" for k, v in (call.get("args") or {}).items()
        )
        lines.append(f"🔧 `{call.get('name')}({args})`")
    return lines


def _parse(iso):
    try:
        return datetime.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def build_clean_history(messages) -> list[dict]:
    turns: list[dict] = []
    for msg in messages:
        name = getattr(msg, "name", "") or ""
        if msg.type == "human":
            turns.append({"human": None if name in HIDDEN_NAMES else msg, "ai": []})
        elif msg.type == "ai" and name != "Qwen3-Coder (Context Gatherer)":
            if not turns:
                turns.append({"human": None, "ai": []})
            turns[-1]["ai"].append(msg)

    out: list[dict] = []
    for turn in turns:
        human = turn["human"]
        if human is not None and _text(human.content).strip():
            out.append({
                "id": human.id,
                "role": "user",
                "content": _text(human.content),
                "created_at": human.additional_kwargs.get("created_at"),
            })

        thoughts: list[str] = []
        candidates = []  # (msg, answer, reasoning)
        for ai in turn["ai"]:
            answer, reasoning = split_reasoning(_text(ai.content))
            reasoning = "\n\n".join(
                p for p in (ai.additional_kwargs.get("reasoning_content") or "", reasoning) if p
            )
            if getattr(ai, "tool_calls", None):
                body = "\n".join(([answer] if answer else []) + _tool_lines(ai))
                if reasoning:
                    body = reasoning + "\n\n" + body
                thoughts.append(body)
            elif answer:
                candidates.append((ai, answer, reasoning))
            elif reasoning:
                thoughts.append(reasoning)

        if not candidates:
            continue

        for ai, answer, reasoning in candidates[:-1]:
            label = f"**{ai.name}**\n\n" if getattr(ai, "name", None) else ""
            thoughts.append(label + (reasoning + "\n\n" if reasoning else "") + answer)

        final, answer, reasoning = candidates[-1]
        if reasoning:
            thoughts.append(reasoning)

        created = final.additional_kwargs.get("created_at")
        elapsed = final.additional_kwargs.get("elapsed_seconds")
        start = _parse(human.additional_kwargs.get("created_at")) if human else None
        end = _parse(created)
        if start and end and end >= start:
            elapsed = round((end - start).total_seconds(), 2)

        out.append({
            "id": final.id,
            "role": "assistant",
            "content": answer,
            "model": getattr(final, "name", None),
            "thoughts": "\n\n---\n\n".join(t for t in thoughts if t.strip()) or None,
            "created_at": created,
            "elapsed_seconds": elapsed,
        })
    return out
