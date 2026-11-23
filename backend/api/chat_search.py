"""Busca global em títulos, pastas, tags e conteúdo das mensagens das conversas."""

from __future__ import annotations

import asyncio
import re
import unicodedata

from backend.api.history import build_clean_history


def normalize_search(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    no_accents = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def _find_match_span(original: str, norm_query: str) -> tuple[int, int] | None:
    """Encontra o intervalo (start, end) aproximado no texto original ignorando acentos e maiúsculas."""
    if not original or not norm_query:
        return None
    chars: list[str] = []
    pos_map: list[int] = []
    for idx, ch in enumerate(original):
        decomposed = unicodedata.normalize("NFKD", ch)
        for sub in decomposed:
            if unicodedata.combining(sub):
                continue
            chars.append(" " if sub.isspace() else sub.lower())
            pos_map.append(idx)
    flat = "".join(chars)
    found = flat.find(norm_query)
    if found == -1:
        collapsed_chars: list[str] = []
        collapsed_map: list[int] = []
        prev_space = False
        for c, p in zip(chars, pos_map):
            if c == " ":
                if not prev_space:
                    collapsed_chars.append(" ")
                    collapsed_map.append(p)
                prev_space = True
            else:
                collapsed_chars.append(c)
                collapsed_map.append(p)
                prev_space = False
        flat = "".join(collapsed_chars)
        pos_map = collapsed_map
        found = flat.find(norm_query)
        if found == -1:
            return None
    end_idx = min(found + len(norm_query) - 1, len(pos_map) - 1)
    return pos_map[found], pos_map[end_idx] + 1


def make_snippet(text: str, norm_query: str, radius: int = 80) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if not clean:
        return ""
    span = _find_match_span(clean, norm_query)
    if span is None:
        return clean[: radius * 2] + ("…" if len(clean) > radius * 2 else "")
    start, end = span
    left = max(0, start - radius)
    right = min(len(clean), end + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(clean) else ""
    return f"{prefix}{clean[left:right].strip()}{suffix}"


async def search_chats_and_messages(
    chats: list[dict],
    app_graph,
    query: str,
    limit: int = 30,
    max_chats: int = 120,
    max_per_chat: int = 2,
) -> list[dict]:
    norm_q = normalize_search(query)
    if len(norm_q) < 2:
        return []

    subset = list(chats)[:max_chats]
    sem = asyncio.Semaphore(8)

    async def inspect_chat(chat: dict) -> list[dict]:
        hits: list[dict] = []
        title = str(chat.get("title") or "")
        folder = str(chat.get("folder") or "")
        tags = list(chat.get("tags") or [])
        pinned = bool(chat.get("pinned"))

        if norm_q in normalize_search(title) or norm_q in normalize_search(folder) or any(norm_q in normalize_search(t) for t in tags):
            hits.append(
                {
                    "chat_id": chat["id"],
                    "thread_id": chat["thread_id"],
                    "title": title,
                    "folder": folder,
                    "pinned": pinned,
                    "tags": tags,
                    "match_in": "title",
                    "role": None,
                    "message_id": None,
                    "snippet": title,
                    "created_at": str(chat.get("created_at") or ""),
                }
            )

        if app_graph is None:
            return hits

        async with sem:
            try:
                snapshot = await app_graph.aget_state({"configurable": {"thread_id": chat["thread_id"]}})
            except Exception:  # noqa: BLE001
                return hits

        values = getattr(snapshot, "values", None) or {}
        raw_messages = values.get("messages") or []
        if not raw_messages:
            return hits

        clean_msgs = build_clean_history(raw_messages)
        msg_hits = 0
        for msg in reversed(clean_msgs):
            content = str(msg.get("content") or "")
            if norm_q in normalize_search(content):
                hits.append(
                    {
                        "chat_id": chat["id"],
                        "thread_id": chat["thread_id"],
                        "title": title,
                        "folder": folder,
                        "pinned": pinned,
                        "tags": tags,
                        "match_in": "message",
                        "role": msg.get("role"),
                        "message_id": msg.get("id"),
                        "snippet": make_snippet(content, norm_q),
                        "created_at": str(msg.get("created_at") or chat.get("created_at") or ""),
                    }
                )
                msg_hits += 1
                if msg_hits >= max_per_chat:
                    break
        return hits

    batches = await asyncio.gather(*(inspect_chat(c) for c in subset))
    results: list[dict] = []
    for group in batches:
        results.extend(group)

    results.sort(
        key=lambda item: (
            0 if item["match_in"] == "message" else 1,
            0 if item["pinned"] else 1,
        )
    )
    return results[:limit]
