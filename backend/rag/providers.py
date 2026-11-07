"""Embeddings e resumos atrás de interfaces simples e trocáveis.

- OllamaEmbedder / OllamaSummarizer: usam a API HTTP do Ollama (só stdlib).
- HashEmbedder: determinístico e offline (testes, demonstração).
- HeuristicSummarizer: resumo sem LLM (docstring, assinatura, nomes). É também o
  plano B quando o LLM falha, para a ingestão nunca travar.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import textwrap
import time
import urllib.error
import urllib.request
from typing import Protocol

from .entities import Chunk


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Summarizer(Protocol):
    def summarize(self, chunk: Chunk) -> str: ...


def _post_json(url: str, payload: dict, timeout: float, retries: int = 2) -> dict:
    data = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Falha ao chamar {url}: {last}")


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, dim: int, timeout: float = 120.0) -> None:
        self.base_url, self.model, self.dim, self.timeout = base_url.rstrip("/"), model, dim, timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = _post_json(f"{self.base_url}/api/embed",
                          {"model": self.model, "input": texts, "truncate": True}, self.timeout)
        vectors = body.get("embeddings") or []
        if len(vectors) != len(texts):
            raise RuntimeError(f"O Ollama devolveu {len(vectors)} embeddings para {len(texts)} textos.")
        if vectors and len(vectors[0]) != self.dim:
            raise RuntimeError(
                f"Dimensão do embedding ({len(vectors[0])}) difere de RAG_EMBED_DIM ({self.dim}). "
                f"Ajuste RAG_EMBED_DIM para o modelo '{self.model}'."
            )
        return vectors


class HashEmbedder:
    """Bag-of-words com hash: sem modelo, sem rede. Serve para testes e demonstração."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim
        self.calls = 0  # quantos textos foram embutidos (útil para testar o incremental)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(token.encode()).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


# ── resumo ───────────────────────────────────────────────────────────────
def _first_sentence(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return cut[:limit]


def _strip_numbers(code: str) -> str:
    return "\n".join(re.sub(r"^\d+:\s?", "", line) for line in code.split("\n"))


class HeuristicSummarizer:
    def summarize(self, chunk: Chunk) -> str:
        code = textwrap.dedent(chunk.code)
        if chunk.kind in {"header", "constants"}:
            names = re.findall(r"^([A-Z][A-Z0-9_]{2,})\s*[:=]", code, re.MULTILINE)
            imports = re.findall(r"^(?:from\s+(\S+)\s+import|import\s+(\S+))", code, re.MULTILINE)
            mods = [a or b for a, b in imports][:6]
            parts = []
            if names:
                parts.append("define " + ", ".join(dict.fromkeys(names)))
            if mods:
                parts.append("importa " + ", ".join(dict.fromkeys(mods)))
            return f"Cabeçalho de {chunk.path}: " + ("; ".join(parts) or "imports e configuração") + "."
        if chunk.language == "python" and chunk.kind in {"function", "method", "class", "class_skeleton"}:
            try:
                node = ast.parse(code).body[0]
            except (SyntaxError, IndexError):
                node = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc:
                    return _first_sentence(doc)
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    return f"Classe {node.name}" + (f" com métodos {', '.join(methods[:6])}." if methods else ".")
                args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
                calls = []
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        f = sub.func
                        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                        if name and name not in calls:
                            calls.append(name)
                what = "Método" if chunk.kind == "method" else "Função"
                uses = f" Usa: {', '.join(calls[:6])}." if calls else ""
                return f"{what} {chunk.qualname}({', '.join(args)}).{uses}"
        first = next((ln.strip() for ln in code.split("\n") if ln.strip()), "")
        return f"{chunk.kind} {chunk.qualname}: {first[:100]}"


class OllamaSummarizer:
    """Uma frase por trecho, via LLM local. Se falhar, cai no resumo heurístico."""

    PROMPT = (
        "Resuma em UMA frase curta (no máximo 25 palavras, em português) o que o trecho de código abaixo faz. "
        "Cite nomes reais que aparecem no código. Não invente nada. Responda só com a frase.\n\n"
        "Arquivo: {path}\nSímbolo: {qualname}\n\n{code}"
    )

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.fallback = HeuristicSummarizer()

    def summarize(self, chunk: Chunk) -> str:
        prompt = self.PROMPT.format(path=chunk.path, qualname=chunk.qualname, code=_strip_numbers(chunk.code)[:5000])
        try:
            body = _post_json(
                f"{self.base_url}/api/generate",
                {"model": self.model, "prompt": prompt, "stream": False,
                 "options": {"temperature": 0.1, "num_predict": 80}},
                self.timeout, retries=1,
            )
            text = " ".join(str(body.get("response", "")).split())
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            if text:
                return text[:240]
        except RuntimeError:
            pass
        return self.fallback.summarize(chunk)
