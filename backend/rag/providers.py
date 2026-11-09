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
    kind: str  # 'heuristic' ou 'llm:<modelo>'

    def summarize(self, chunk: Chunk) -> str: ...


def _post_json(url: str, payload: dict, timeout: float, retries: int = 2) -> dict:
    data = json.dumps(payload).encode("utf-8")
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Inclui o corpo da resposta do Ollama (ex.: "model 'x' not found"), que o urllib esconde.
            detail = ""
            try:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                    detail = str(parsed.get("error", raw)) if isinstance(parsed, dict) else raw
                except ValueError:
                    detail = raw
            except Exception:
                detail = ""
            detail = " ".join(detail.split())[:200]
            last = RuntimeError(f"{exc}" + (f" - {detail}" if detail else ""))
            if exc.code < 500 and exc.code not in (408, 429):
                break  # erro do cliente (404 modelo inexistente, 400...): repetir não resolve
            time.sleep(0.5 * (attempt + 1))
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


class Summary(str):
    """Texto do resumo + de onde ele veio: 'heuristic' ou 'llm:<modelo>'."""

    kind: str = "heuristic"

    def __new__(cls, text: str, kind: str = "heuristic"):
        obj = super().__new__(cls, text)
        obj.kind = kind
        return obj


# Chamadas genéricas que só poluem o resumo ("Usa: get, strip, append...")
_NOISE_CALLS = {
    "get", "post", "put", "patch", "delete", "head", "options", "append", "extend", "add", "update", "pop", "items",
    "keys", "values", "join", "split", "strip", "lstrip", "rstrip", "replace", "format", "startswith", "endswith",
    "lower", "upper", "encode", "decode", "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
    "isinstance", "getattr", "hasattr", "setattr", "print", "range", "enumerate", "sorted", "reversed", "min", "max",
    "sum", "any", "all", "zip", "map", "filter", "open", "type", "super", "iter", "next", "cast", "copy", "sub",
}
_HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _decorator_label(node: ast.AST) -> str:
    """'endpoint POST /chat' para rotas web; 'tool do agente' para @tool; vazio nos demais casos."""
    for dec in getattr(node, "decorator_list", []):
        call = dec if isinstance(dec, ast.Call) else None
        func = call.func if call else dec
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if not name:
            continue
        if call and name.lower() in _HTTP_VERBS and call.args:
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return f"endpoint {name.upper()} {first.value}"
        if name == "tool":
            return "tool do agente"
    return ""


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _body_calls(node: ast.AST, limit: int = 6) -> list[str]:
    """Funções que o CORPO chama (decoradores ficam de fora), sem as genéricas."""
    found: list[str] = []
    for stmt in getattr(node, "body", []):
        for sub in ast.walk(stmt):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if name and name not in _NOISE_CALLS and name not in found:
                found.append(name)
    return found[:limit]


class HeuristicSummarizer:
    kind = "heuristic"

    def reset(self) -> None:
        return None

    def probe(self) -> tuple[bool, str]:
        return True, ""

    def describe(self) -> dict:
        return {"kind": "heuristic"}

    def summarize(self, chunk: Chunk) -> Summary:
        return Summary(self._text(chunk), "heuristic")

    def _text(self, chunk: Chunk) -> str:
        code = textwrap.dedent(chunk.symbol_code or chunk.code)

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

        if chunk.kind == "constant":
            try:
                value = ast.parse(code).body[0].value  # type: ignore[attr-defined]
            except (SyntaxError, IndexError, AttributeError):
                value = None
            first = ""
            texts = []
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                texts = [value.value]
            elif isinstance(value, ast.JoinedStr):
                texts = [p.value for p in value.values if isinstance(p, ast.Constant) and isinstance(p.value, str)]
            for text in texts:
                first = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
                if first:
                    break
            size = code.count("\n") + 1
            return f"Constante {chunk.qualname} ({size} linhas)" + (f": {first[:100]}" if first else ".")

        if chunk.language == "python" and chunk.kind in {"function", "method", "class", "class_skeleton"}:
            try:
                node = ast.parse(code).body[0]
            except (SyntaxError, IndexError):
                node = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                label = _decorator_label(node)
                doc = ast.get_docstring(node)
                if doc:
                    sentence = _first_sentence(doc)
                    return f"{_cap(label)}: {sentence}" if label else sentence
                if isinstance(node, ast.ClassDef):
                    bases = [b.id if isinstance(b, ast.Name) else getattr(b, "attr", "?") for b in node.bases]
                    fields = [s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)]
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    text = f"Classe {node.name}" + (f"({', '.join(bases)})" if bases else "")
                    extras = []
                    if fields:
                        extras.append("campos " + ", ".join(fields[:8]))
                    if methods:
                        extras.append("métodos " + ", ".join(methods[:6]))
                    return text + (" com " + " e ".join(extras) if extras else "") + "."
                args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
                calls = _body_calls(node)
                head = f"{_cap(label)}:" if label else ("Método" if chunk.kind == "method" else "Função")
                uses = f" Usa: {', '.join(calls)}." if calls else ""
                return f"{head} {chunk.qualname}({', '.join(args)}).{uses}"

        first = next((ln.strip() for ln in code.split("\n") if ln.strip()), "")
        return f"{chunk.kind} {chunk.qualname}: {first[:100]}"


class OllamaSummarizer:
    """Uma frase por trecho, via LLM local. Se a IA falhar, cai no heurístico e REGISTRA o motivo."""

    MAX_CONSECUTIVE_FAILURES = 5  # depois disso a IA é desligada até o fim da ingestão (evita esperar timeouts)

    PROMPT = (
        "Resuma em UMA frase curta (no máximo 25 palavras, em português) o que o trecho de código abaixo faz "
        "e para que serve. Cite nomes reais que aparecem no código. Não invente nada. Responda só com a frase.\n\n"
        "Arquivo: {path}\nSímbolo: {qualname}\n\n{code}"
    )

    def __init__(self, base_url: str, model: str, timeout: float = 180.0, think: str = "") -> None:
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.kind = f"llm:{model}"
        self.fallback = HeuristicSummarizer()
        self.last_error = ""
        self.disabled = False
        self.failures = 0
        # Modelos de raciocínio (gpt-oss, qwen3...) gastam tokens "pensando": limite o esforço.
        # RAG_SUMMARY_THINK: vazio/auto, low|medium|high, true, off.
        choice = (think or "").strip().lower()
        if choice in {"", "auto"}:
            self.think: str | bool | None = "low" if "gpt-oss" in model.lower() else None
        elif choice in {"off", "false", "no", "0", "none"}:
            self.think = None
        elif choice in {"true", "on", "1"}:
            self.think = True
        else:
            self.think = choice

    def reset(self) -> None:
        """Nova ingestão: volta a tentar a IA."""
        self.disabled = False
        self.failures = 0

    def describe(self) -> dict:
        return {"kind": self.kind, "model": self.model, "think": self.think, "ollama_url": self.base_url,
                "timeout": self.timeout}

    def _call(self, prompt: str, num_predict: int) -> dict:
        payload: dict = {
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.1, "num_predict": num_predict},
        }
        if self.think is not None:
            payload["think"] = self.think
        url = f"{self.base_url}/api/generate"
        try:
            return _post_json(url, payload, self.timeout, retries=1)
        except RuntimeError as exc:
            if self.think is not None and "400" in str(exc):  # o modelo não aceita 'think'
                self.think = None
                payload.pop("think", None)
                return _post_json(url, payload, self.timeout, retries=1)
            if "404" in str(exc):
                raise RuntimeError(
                    f"Modelo '{self.model}' nao encontrado no Ollama ({self.base_url}): "
                    f"rode 'ollama pull {self.model}' ou ajuste RAG_SUMMARY_MODEL/OLLAMA_BASE_URL. "
                    f"Detalhe: {exc}"
                ) from exc
            raise

    @staticmethod
    def _clean(body: dict) -> str:
        text = " ".join(str(body.get("response", "")).split())
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _generate(self, prompt: str) -> str:
        """Texto limpo, ou '' (com last_error explicando). Resposta vazia em modelo de raciocínio é resgatada."""
        body = self._call(prompt, 512)
        text = self._clean(body)
        if not text and self.think is None:
            # O limite de tokens acabou durante o "pensamento": tenta UMA vez pedindo raciocínio curto.
            self.think = "low"
            body = self._call(prompt, 1024)
            text = self._clean(body)
        if not text:
            self.last_error = (
                f"resposta vazia (done_reason={body.get('done_reason')}); "
                "modelos de raciocínio podem gastar o limite de tokens pensando"
            )
        return text

    def probe(self) -> tuple[bool, str]:
        """Teste rápido antes de uma ingestão: (funcionou?, motivo da falha)."""
        self.reset()
        self.last_error = ""
        try:
            text = self._generate("Responda apenas com a palavra: ok")
        except RuntimeError as exc:
            return False, str(exc)[:300]
        return (True, "") if text else (False, self.last_error)

    def summarize(self, chunk: Chunk) -> Summary:
        if self.disabled:
            return Summary(self.fallback._text(chunk), "heuristic")
        code = _strip_numbers(chunk.symbol_code or chunk.code)[:5000]
        prompt = self.PROMPT.format(path=chunk.path, qualname=chunk.qualname, code=code)
        try:
            text = self._generate(prompt)
            if text:
                self.failures = 0
                return Summary(text[:240], self.kind)
        except RuntimeError as exc:
            self.last_error = str(exc)[:300]
        self.failures += 1
        if self.failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.disabled = True
            self.last_error += f" (IA desligada nesta ingestão após {self.failures} falhas seguidas)"
        return Summary(self.fallback._text(chunk), "heuristic")
