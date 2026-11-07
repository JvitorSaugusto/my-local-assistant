"""Mapa do repositório em árvore: pasta > arquivo > classe > função/método."""

from __future__ import annotations


def build_repo_map(rows: list[dict], max_summary: int = 90) -> str:
    """`rows`: path, kind, qualname, parent, start_line, end_line, summary (ordem livre)."""
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

    def render(node: dict, depth: int) -> None:
        pad = "  " * depth
        for name in sorted(node, key=lambda n: (not n.endswith("/"), n.lower())):
            value = node[name]
            if isinstance(value, dict):
                out.append(f"{pad}{name}")
                render(value, depth + 1)
                continue
            out.append(f"{pad}{name}")
            symbols = [r for r in value if r["kind"] not in {"header", "constants"} and r.get("part", 1) in (1, None)]
            for r in sorted(symbols, key=lambda r: r["start_line"]):
                label = {"class": "class", "class_skeleton": "class", "method": "def", "function": "def"}.get(r["kind"], r["kind"])
                indent = "  " * (depth + 1 + (1 if r.get("parent") else 0))
                short = (r.get("summary") or "").strip().replace("\n", " ")
                if len(short) > max_summary:
                    short = short[: max_summary - 1] + "…"
                tail = f" — {short}" if short else ""
                out.append(f"{indent}{label} {r['qualname'].split('.')[-1]} (L{r['start_line']}-{r['end_line']}){tail}")

    render(tree, 0)
    return "\n".join(out)
