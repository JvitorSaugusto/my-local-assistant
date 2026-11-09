"""Mapa do repositório em árvore: pasta > arquivo > classe > função/método."""

from __future__ import annotations


_NAME_KINDS = {"class", "class_skeleton", "method", "function"}
_LABEL = {"class": "class", "class_skeleton": "class", "method": "def", "function": "def", "constant": "const"}


def _merge_symbols(items: list[dict]) -> list[dict]:
    """Junta as partes de um mesmo símbolo (função grande) numa linha só, com o intervalo completo."""
    merged: dict[tuple, dict] = {}
    for row in items:
        if row["kind"] in {"header", "constants"}:
            continue
        key = (row["kind"], row["qualname"], row.get("parent") or "")
        current = merged.get(key)
        if current is None:
            merged[key] = dict(row)
            continue
        current["start_line"] = min(current["start_line"], row["start_line"])
        current["end_line"] = max(current["end_line"], row["end_line"])
        if not current.get("summary") and row.get("summary"):
            current["summary"] = row["summary"]
    return sorted(merged.values(), key=lambda r: r["start_line"])


def build_repo_map(rows: list[dict], max_summary: int = 90) -> str:
    """`rows`: path, kind, qualname, parent, start_line, end_line, summary, part (ordem livre)."""
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        by_file.setdefault(row["path"], []).append(row)

    tree: dict = {}
    for path in sorted(by_file):
        node = tree
        parts = path.split("/")
        for folder in parts[:-1]:
            node = node.setdefault(folder + "/", {})
        node[parts[-1]] = by_file[path]

    out: list[str] = []

    def short(text: str | None) -> str:
        text = (text or "").strip().replace("\n", " ")
        if len(text) > max_summary:
            text = text[: max_summary - 1] + "…"
        return f" — {text}" if text else ""

    def render(node: dict, depth: int) -> None:
        pad = "  " * depth
        for name in sorted(node, key=lambda n: (not n.endswith("/"), n.lower())):
            value = node[name]
            if isinstance(value, dict):
                out.append(f"{pad}{name}")
                render(value, depth + 1)
                continue
            out.append(f"{pad}{name}")
            symbols = _merge_symbols(value)
            if not symbols:
                head = next((r for r in value if r["kind"] in {"header", "constants"}), None)
                if head:
                    out.append(f"{'  ' * (depth + 1)}(só cabeçalho/constantes){short(head.get('summary'))}")
                continue
            for r in symbols:
                label = _LABEL.get(r["kind"], r["kind"])
                shown = r["qualname"].split(".")[-1] if r["kind"] in _NAME_KINDS else r["qualname"]
                indent = "  " * (depth + 1 + (1 if r.get("parent") else 0))
                out.append(f"{indent}{label} {shown} (L{r['start_line']}-{r['end_line']}){short(r.get('summary'))}")

    render(tree, 0)
    return "\n".join(out)
