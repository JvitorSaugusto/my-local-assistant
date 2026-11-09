"""Entidades do RAG de código (dados puros, sem dependências externas)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()


@dataclass(frozen=True)
class FileInfo:
    path: str  # relativo à raiz, com "/"
    abs_path: str
    size: int
    sha1: str
    language: str


@dataclass
class Chunk:
    """Um trecho de código com identidade: classe, função/método, cabeçalho ou bloco."""

    path: str
    language: str
    kind: str  # header | constants | class | class_skeleton | function | method | block | section
    qualname: str  # ex.: "OSMobileSignupSyncView.post"
    parent: str  # classe pai ("" se não houver)
    start_line: int
    end_line: int
    code: str
    part: int = 1
    parts: int = 1
    summary: str = ""
    symbol_code: str = ""  # código do símbolo INTEIRO (quando o chunk é só uma parte dele)
    content_hash: str = field(default="")

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = sha1_text(self.code)

    def tag(self) -> str:
        """Etiqueta que acompanha o trecho: onde ele vive e o que ele faz."""
        lines = [f"[arquivo] {self.path}", f"[tipo] {self.kind}"]
        if self.parent:
            lines.append(f"[classe] {self.parent}")
        where = f"[símbolo] {self.qualname} (linhas {self.start_line}-{self.end_line})"
        if self.parts > 1:
            where += f" parte {self.part}/{self.parts}"
        lines.append(where)
        if self.summary:
            lines.append(f"[resumo] {self.summary}")
        return "\n".join(lines)

    def embed_text(self, limit: int = 6000) -> str:
        return (self.tag() + "\n\n" + self.code)[:limit]


@dataclass
class SearchHit:
    chunk_id: int
    path: str
    kind: str
    qualname: str
    start_line: int
    end_line: int
    summary: str
    content: str
    score: float = 0.0
    matched_by: list[str] = field(default_factory=list)
