"""Raciocínio e ações ao vivo: acompanha a execução do grafo (FastAPI e Celery).

Em vez de exibir apenas código cru ou ficar travado em "Executando...", traduz cada etapa e
tool call em ações claras ("Lendo arquivo X", "Criando arquivo Y", "Rodando testes...") e
espelha o estado em arquivo leve temporário quando roda no worker Celery para o frontend
exibir o progresso em tempo real.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

LIVE_ENABLED = os.getenv("LIVE_THOUGHTS", "1").strip().lower() not in ("0", "false", "no", "off")
MAX_SEG_CHARS = 8000
MAX_SEGS = 60
_LIVE_DIR = Path(tempfile.gettempdir()) / "assistente_local_live"

NODE_LABELS = {
    "router_node": "Escolhendo o melhor modo",
    "enhancer_node": "Refinando o pedido",
    "standard_node_20b": "Preparando resposta",
    "code_node": "Analisando código",
    "note_draft_node": "Estruturando nota",
    "note_refine_node": "Refinando nota",
    "context_gatherer_node": "Coletando contexto do projeto",
    "heavy_analyzer_node": "Analisando arquitetura e plano",
    "generate_node": "Implementando tarefa",
    "generate_dispatch_node": "Despachando tarefas",
    "summarize_node": "Resumindo conversa",
    "ops_node": "Executando operação de projeto",
    "audit_node": "Executando auditoria",
    "tools": "Executando ferramenta",
}


def _short_path(path: str) -> str:
    clean = str(path or "").strip().replace("\\", "/")
    parts = [p for p in clean.split("/") if p]
    if len(parts) <= 2:
        return clean
    return "/".join(parts[-2:])


def _parse_partial_args(raw: str) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    out: dict[str, str] = {}
    for key in ("file_path", "path", "dir_path", "query", "pattern", "command", "base_url", "queries", "subpath", "action"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', text)
        if m:
            out[key] = m.group(1)
    for key in ("start_line", "end_line", "offset"):
        m = re.search(rf'"{key}"\s*:\s*(\d+)', text)
        if m:
            out[key] = m.group(1)
    return out


def humanize_tool_call(name: str, args_raw: str) -> str:
    """Converte uma chamada de ferramenta em uma frase curta, clara e dinâmica."""
    n = str(name or "").strip()
    a = _parse_partial_args(args_raw)
    fp = _short_path(a.get("file_path") or a.get("path") or "")
    dp = _short_path(a.get("dir_path") or "")

    if n == "read_file_content":
        return f"📖 Lendo {fp}" if fp else "📖 Lendo arquivo do projeto"
    if n == "read_file_chunk":
        off = a.get("offset")
        loc = f" (linha {off})" if off else ""
        return f"📖 Lendo trecho de {fp}{loc}" if fp else "📖 Lendo trecho de arquivo"
    if n == "read_attachment":
        return f"📎 Lendo anexo {fp}" if fp else "📎 Lendo arquivo anexado"
    if n == "search_in_file":
        pat = str(a.get("pattern") or "")[:36]
        return f"🔍 Buscando '{pat}' em {fp}" if (pat and fp) else f"🔍 Buscando no arquivo {fp or '...'}"
    if n == "search_codebase":
        q = str(a.get("query") or "")[:40]
        return f"🔎 Pesquisando no índice por '{q}'" if q else "🔎 Pesquisando no código do projeto"
    if n == "list_directory_files":
        return f"📁 Listando arquivos em {dp or '.'}"
    if n == "generate_repo_map":
        return f"🗺️ Mapeando estrutura de {dp or 'todo o projeto'}"
    if n == "create_new_file":
        return f"📝 Criando arquivo {fp}" if fp else "📝 Criando novo arquivo"
    if n in ("edit_existing_file", "replace_in_file", "batch_edit_file", "append_to_file"):
        s, e = a.get("start_line"), a.get("end_line")
        span = f" (linhas {s}-{e})" if (s and e) else ""
        return f"✏️ Editando {fp}{span}" if fp else "✏️ Editando arquivo"
    if n == "write_markdown_file":
        return f"📄 Escrevendo documento {fp}" if fp else "📄 Escrevendo Markdown"
    if n == "create_pdf_file":
        return f"📕 Gerando PDF {fp}" if fp else "📕 Gerando arquivo PDF"
    if n == "run_tests":
        return f"🧪 Rodando testes em {fp}" if fp else "🧪 Rodando suíte de testes (pytest)"
    if n == "validate_python_syntax":
        return f"✅ Validando sintaxe Python de {fp}" if fp else "✅ Validando sintaxe Python"
    if n == "run_safe_command":
        cmd = str(a.get("command") or "")[:50]
        return f"⚙️ Executando `{cmd}`" if cmd else "⚙️ Executando comando de diagnóstico"
    if n in ("local_http_check", "test_local_routes"):
        url = str(a.get("base_url") or a.get("url") or "localhost")[:45]
        return f"🌐 Testando rotas locais em {url}"
    if n == "docker_monitor_control":
        act = str(a.get("action") or "status")
        return f"🐳 Monitor Docker ({act})"
    if n == "extract_code_snippets":
        q = str(a.get("queries") or "")[:45]
        return f"✂️ Extraindo trechos completos ({q})" if q else "✂️ Extraindo trechos de código"
    if n in ("web_search", "web_fetch"):
        q = str(a.get("query") or a.get("url") or "")[:45]
        return f"🌍 Consultando web: {q}" if q else "🌍 Pesquisando na web"
    if n == "create_git_branch":
        return "🌿 Preparando branch de trabalho"
    return f"🔧 Executando {n}"


def humanize_tool_result(name: str, content: str) -> str:
    """Resumo curto (1 linha) do retorno da ferramenta sem despejar código cru."""
    text = str(content or "").strip()
    low = text.lower()
    n = str(name or "").strip()
    if low.startswith(("erro", "error")) or "edição rejeitada" in low:
        first = text.splitlines()[0][:110] if text else "erro"
        return f"⚠️ {first}"
    if n == "run_tests":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        tail = lines[-1][:110] if lines else "testes finalizados"
        icon = "✅" if ("passed" in tail.lower() and "failed" not in tail.lower()) else "🧪"
        return f"{icon} {tail}"
    if n in ("create_new_file", "edit_existing_file", "replace_in_file", "batch_edit_file", "append_to_file"):
        return "✅ Arquivo atualizado"
    if n == "validate_python_syntax":
        return "✅ Sintaxe válida" if "ok" in low or "válid" in low else text.splitlines()[0][:100]
    lines_count = len(text.splitlines())
    return f"✓ Concluído ({lines_count} linha(s))" if lines_count > 1 else (text[:100] or "✓ Concluído")


def _live_file_for(thread_id: str) -> Path:
    digest = hashlib.sha256(str(thread_id).encode("utf-8")).hexdigest()[:24]
    return _LIVE_DIR / f"live_{digest}.json"


def _write_persisted_snapshot(thread_id: str, snap: dict) -> None:
    try:
        _LIVE_DIR.mkdir(parents=True, exist_ok=True)
        target = _live_file_for(thread_id)
        tmp = target.with_suffix(".tmp")
        payload = {**snap, "_updated_at": time.time()}
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


def _read_persisted_snapshot(thread_id: str) -> dict | None:
    target = _live_file_for(thread_id)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        updated = float(data.get("_updated_at") or 0)
        # Ignora arquivos abandonados há mais de 30 minutos
        if time.time() - updated > 1800:
            return None
        return data
    except (OSError, ValueError):
        return None


def split_think(text: str) -> tuple[str, str]:
    """(resposta, raciocínio) a partir de <think>…</think>, inclusive bloco ainda aberto ou sem abertura."""
    if not text:
        return "", ""
    parts = [p.strip() for p in re.findall(r"<think>(.*?)</think>", text, flags=re.S | re.I)]
    answer = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    low = answer.lower()
    if "<think>" in low:
        i = low.index("<think>")
        parts.append(answer[i + 7 :].strip())
        answer = answer[:i]
    elif "</think>" in low:
        i = low.index("</think>")
        parts.insert(0, answer[:i].strip())
        answer = answer[i + 8 :]
    return answer.strip(), "\n\n".join(p for p in parts if p)


def chunk_parts(chunk) -> tuple[str, str, list[tuple[int, str, str]]]:
    """Separa um pedaço do stream em (texto, raciocínio, [(índice, nome, args)] de chamadas de ferramenta)."""
    text, reasoning = "", ""
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                text += block
            elif isinstance(block, dict):
                kind = block.get("type")
                if kind in ("thinking", "reasoning"):
                    reasoning += str(block.get("thinking") or block.get("reasoning") or block.get("text") or "")
                elif kind == "text":
                    text += str(block.get("text") or "")
    extra = getattr(chunk, "additional_kwargs", None) or {}
    reasoning += str(extra.get("reasoning_content") or "")
    calls = []
    for call in getattr(chunk, "tool_call_chunks", None) or []:
        calls.append((call.get("index") or 0, call.get("name") or "", call.get("args") or ""))
    return text, reasoning, calls


class LiveBuffer:
    def __init__(self, thread_id: str = "", persist: bool = False):
        self.thread_id = thread_id
        self.persist = persist
        self.lock = threading.Lock()
        self.seq = 0
        self.running = True
        self.started = time.time()
        self.segs: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.seen: int | None = None
        self._last_flush = 0.0

    def _flush_if_needed(self, force: bool = False) -> None:
        if not self.persist or not self.thread_id:
            return
        now = time.time()
        if not force and (now - self._last_flush) < 0.7:
            return
        self._last_flush = now
        snap = self._build_snapshot_unlocked(-1)
        _write_persisted_snapshot(self.thread_id, snap)

    def _seg(self, key: str, node: str, label: str | None = None) -> dict:
        seg = self.by_key.get(key)
        if seg is None:
            for old in self.segs:
                old["done"] = True
            seg = {
                "id": key,
                "node": node,
                "label": label or NODE_LABELS.get(node, node or "Modelo"),
                "raw": "",
                "reasoning": "",
                "calls": {},
                "tool_name": "",
                "tool_text": "",
                "done": False,
            }
            self.by_key[key] = seg
            self.segs.append(seg)
            if len(self.segs) > MAX_SEGS:
                drop = self.segs.pop(0)
                self.by_key.pop(drop["id"], None)
        return seg

    def add_chunk(self, chunk, meta: dict | None):
        meta = meta or {}
        node = str(meta.get("langgraph_node") or "")
        text, reasoning, calls = chunk_parts(chunk)
        if not (text or reasoning or calls):
            return
        with self.lock:
            seg = self._seg(f"{node}:{meta.get('langgraph_step')}", node)
            seg["raw"] = (seg["raw"] + text)[-MAX_SEG_CHARS:]
            seg["reasoning"] = (seg["reasoning"] + reasoning)[-MAX_SEG_CHARS:]
            for index, name, args in calls:
                call = seg["calls"].setdefault(index, {"name": "", "args": ""})
                if name:
                    call["name"] = name
                call["args"] = (call["args"] + args)[-600:]
            self.seq += 1
            self._flush_if_needed(force=bool(calls))

    def add_state(self, messages: list):
        """Chamado a cada atualização de estado: registra ferramentas e resultados legíveis."""
        with self.lock:
            if self.seen is None:
                self.seen = len(messages)
                return
            changed = False
            for i in range(self.seen, len(messages)):
                msg = messages[i]
                kind = getattr(msg, "type", "")
                content = getattr(msg, "content", "")
                content = content if isinstance(content, str) else str(content)
                if kind == "tool":
                    tname = getattr(msg, "name", None) or "ferramenta"
                    seg = self._seg(f"tool:{i}", "tools", f"Resultado: {tname}")
                    seg["tool_name"] = tname
                    seg["tool_text"] = content[:500]
                    seg["done"] = True
                    changed = True
                elif kind == "ai":
                    tcalls = getattr(msg, "tool_calls", None) or []
                    if tcalls:
                        seg = self._seg(f"ai_calls:{i}", "", getattr(msg, "name", None) or "Assistente")
                        for idx, c in enumerate(tcalls):
                            seg["calls"][idx] = {
                                "name": str(c.get("name") or ""),
                                "args": json.dumps(c.get("args") or {}, ensure_ascii=False)[:600],
                            }
                        seg["done"] = True
                        changed = True
                    elif content.strip():
                        answer, thought = split_think(content)
                        blob = "".join(s["raw"] + s["reasoning"] for s in self.segs)
                        probe = (answer or thought)[:60]
                        if probe and probe not in blob:
                            seg = self._seg(f"msg:{i}", "", getattr(msg, "name", None) or "Modelo")
                            seg["raw"] = content[-MAX_SEG_CHARS:]
                            seg["done"] = True
                            changed = True
            self.seen = len(messages)
            if changed:
                self.seq += 1
                self._flush_if_needed(force=True)

    def add_progress(self, key: str, label: str, text: str, done: bool = False):
        with self.lock:
            seg = self._seg(key, "audit_node", label)
            seg["label"] = label
            seg["raw"] = str(text or "")[-MAX_SEG_CHARS:]
            seg["done"] = done
            self.seq += 1
            self._flush_if_needed(force=True)

    def finish(self):
        with self.lock:
            self.running = False
            for seg in self.segs:
                seg["done"] = True
            self.seq += 1
            self._flush_if_needed(force=True)

    def _build_snapshot_unlocked(self, after: int = -1) -> dict:
        base = {"running": self.running, "seq": self.seq, "elapsed": round(time.time() - self.started, 1)}
        if after == self.seq:
            return {**base, "changed": False, "headline": "", "actions": [], "segments": []}
        out = []
        actions: list[dict] = []
        for seg in self.segs:
            answer, thought = split_think(seg["raw"])
            reasoning = "\n\n".join(p for p in (seg["reasoning"].strip(), thought) if p)
            tools = []
            human_tools = []
            for call in seg["calls"].values():
                if call["name"]:
                    tools.append(f"→ {call['name']}({call['args'][:200]})")
                    human_tools.append(humanize_tool_call(call["name"], call["args"]))
            if not (answer or reasoning or tools or seg["tool_text"]):
                continue
            for ht in human_tools:
                actions.append({"text": ht, "done": seg["done"]})
            if seg["tool_text"]:
                summary = humanize_tool_result(seg.get("tool_name") or "", seg["tool_text"])
                if actions and not actions[-1].get("detail"):
                    actions[-1]["detail"] = summary
                    actions[-1]["done"] = True
            elif not human_tools and seg["label"] and not seg["label"].startswith("Resultado:"):
                label_txt = f"💭 {seg['label']}"
                if not actions or actions[-1]["text"] != label_txt:
                    actions.append({"text": label_txt, "done": seg["done"]})
            out.append({
                "id": seg["id"],
                "label": seg["label"],
                "done": seg["done"],
                "thought": reasoning,
                "text": answer,
                "tools": tools,
                "human_tools": human_tools,
                "result": seg["tool_text"],
            })
        headline = ""
        if actions:
            headline = actions[-1]["text"]
        elif out:
            headline = out[-1]["label"]
        return {
            **base,
            "changed": True,
            "headline": headline,
            "actions": actions[-12:],
            "segments": out,
        }

    def snapshot(self, after: int = -1) -> dict:
        with self.lock:
            return self._build_snapshot_unlocked(after)


LIVE: dict[str, LiveBuffer] = {}


def live_start(thread_id: str, persist: bool = False) -> LiveBuffer:
    buf = LiveBuffer(thread_id=thread_id, persist=persist)
    LIVE[thread_id] = buf
    if persist:
        _write_persisted_snapshot(thread_id, buf.snapshot(-1))
    return buf


def live_progress(thread_id: str, label: str, text: str, key: str = "audit_progress", done: bool = False) -> None:
    buf = LIVE.get(thread_id)
    if buf is not None:
        buf.add_progress(key, label, text, done=done)


def live_snapshot(thread_id: str, after: int = -1) -> dict:
    buf = LIVE.get(thread_id)
    if buf is not None and buf.running:
        return buf.snapshot(after)
    persisted = _read_persisted_snapshot(thread_id)
    if persisted is not None:
        seq = int(persisted.get("seq") or 0)
        if after == seq:
            return {
                "running": bool(persisted.get("running")),
                "seq": seq,
                "elapsed": persisted.get("elapsed", 0),
                "changed": False,
                "headline": persisted.get("headline", ""),
                "actions": [],
                "segments": [],
            }
        persisted["changed"] = True
        return persisted
    if buf is not None:
        return buf.snapshot(after)
    return {"running": False, "seq": 0, "elapsed": 0, "changed": False, "headline": "", "actions": [], "segments": []}


async def run_graph_live(app_graph, inputs, config, thread_id: str, persist: bool = False):
    """Executa o grafo e devolve o estado final (igual a `ainvoke`), alimentando o buffer ao vivo."""
    if not LIVE_ENABLED:
        return await app_graph.ainvoke(inputs, config=config)
    buf = live_start(thread_id, persist=persist)
    last = None
    try:
        async for mode, data in app_graph.astream(inputs, config=config, stream_mode=["messages", "values"]):
            try:
                if mode == "messages":
                    chunk, meta = data
                    buf.add_chunk(chunk, meta)
                elif mode == "values":
                    last = data
                    buf.add_state(list((data or {}).get("messages") or []))
            except Exception as exc:
                print(f"[LIVE] ignorado: {type(exc).__name__}: {exc}")
    finally:
        buf.finish()
    if last is None:
        snapshot = await app_graph.aget_state(config)
        last = snapshot.values
    return last
