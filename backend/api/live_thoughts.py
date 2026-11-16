"""Raciocínio ao vivo: acompanha a execução do grafo enquanto os modelos pensam.

O POST /api/ai/ continua devolvendo a resposta no fim (nada muda para o resto do front). Enquanto ele roda,
o grafo é executado com `astream` e cada pedaço de texto/raciocínio/ferramenta vai para um buffer por chat;
o front consulta GET /api/ai/{thread_id}/live a cada ~0,8 s e atualiza o balão "Pensando…".

LIVE_THOUGHTS=0 no .env volta ao comportamento antigo (ainvoke, sem balão ao vivo).
"""
import os
import re
import threading
import time

LIVE_ENABLED = os.getenv("LIVE_THOUGHTS", "1").strip().lower() not in ("0", "false", "no", "off")
MAX_SEG_CHARS = 8000
MAX_SEGS = 60

NODE_LABELS = {
    "router_node": "Escolhendo o modo",
    "enhancer_node": "Melhorando o pedido",
    "standard_node_20b": "Modo Normal",
    "code_node": "Modo Code",
    "note_draft_node": "Notas: rascunho",
    "note_refine_node": "Notas: refinando",
    "context_gatherer_node": "Coletando contexto",
    "heavy_analyzer_node": "Heavy: analisando",
    "generate_node": "Gerando",
    "generate_dispatch_node": "Gerando",
    "summarize_node": "Resumindo a conversa",
    "ops_node": "Operações",
    "tools": "Ferramenta",
}


def split_think(text: str) -> tuple[str, str]:
    """(resposta, raciocínio) a partir de <think>…</think>, inclusive bloco ainda aberto ou sem abertura."""
    if not text:
        return "", ""
    parts = [p.strip() for p in re.findall(r"<think>(.*?)</think>", text, flags=re.S | re.I)]
    answer = re.sub(r"<think>.*?</think>", "", text, flags=re.S | re.I)
    low = answer.lower()
    if "<think>" in low:  # aberto e ainda não fechado: o resto é raciocínio
        i = low.index("<think>")
        parts.append(answer[i + 7 :].strip())
        answer = answer[:i]
    elif "</think>" in low:  # modelo que já começa "dentro" do raciocínio
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
    def __init__(self):
        self.lock = threading.Lock()
        self.seq = 0
        self.running = True
        self.started = time.time()
        self.segs: list[dict] = []
        self.by_key: dict[str, dict] = {}
        self.seen: int | None = None

    def _seg(self, key: str, node: str, label: str | None = None) -> dict:
        seg = self.by_key.get(key)
        if seg is None:
            for old in self.segs:
                old["done"] = True
            seg = {"id": key, "node": node, "label": label or NODE_LABELS.get(node, node or "Modelo"),
                   "raw": "", "reasoning": "", "calls": {}, "tool_text": "", "done": False}
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

    def add_state(self, messages: list):
        """Chamado a cada atualização de estado: mostra resultados de ferramentas e mensagens que não vieram em tokens."""
        with self.lock:
            if self.seen is None:  # 1º estado = histórico + pergunta atual: nada disso é "novo"
                self.seen = len(messages)
                return
            for i in range(self.seen, len(messages)):
                msg = messages[i]
                kind = getattr(msg, "type", "")
                content = getattr(msg, "content", "")
                content = content if isinstance(content, str) else str(content)
                if kind == "tool":
                    seg = self._seg(f"tool:{i}", "tools", f"Resultado: {getattr(msg, 'name', None) or 'ferramenta'}")
                    seg["tool_text"] = content[:500]
                    seg["done"] = True
                elif kind == "ai" and content.strip():
                    answer, thought = split_think(content)
                    blob = "".join(s["raw"] + s["reasoning"] for s in self.segs)
                    probe = (answer or thought)[:60]
                    if probe and probe not in blob:  # nó que não transmitiu tokens (ex.: resposta pronta)
                        seg = self._seg(f"msg:{i}", "", getattr(msg, "name", None) or "Modelo")
                        seg["raw"] = content[-MAX_SEG_CHARS:]
                        seg["done"] = True
            self.seen = len(messages)
            self.seq += 1

    def finish(self):
        with self.lock:
            self.running = False
            for seg in self.segs:
                seg["done"] = True
            self.seq += 1

    def snapshot(self, after: int = -1) -> dict:
        with self.lock:
            base = {"running": self.running, "seq": self.seq, "elapsed": round(time.time() - self.started, 1)}
            if after == self.seq:
                return {**base, "changed": False, "segments": []}
            out = []
            for seg in self.segs:
                answer, thought = split_think(seg["raw"])
                reasoning = "\n\n".join(p for p in (seg["reasoning"].strip(), thought) if p)
                tools = []
                for call in seg["calls"].values():
                    if call["name"]:
                        tools.append(f"→ {call['name']}({call['args'][:200]})")
                if not (answer or reasoning or tools or seg["tool_text"]):
                    continue
                out.append({"id": seg["id"], "label": seg["label"], "done": seg["done"],
                            "thought": reasoning, "text": answer, "tools": tools, "result": seg["tool_text"]})
            return {**base, "changed": True, "segments": out}


LIVE: dict[str, LiveBuffer] = {}


def live_start(thread_id: str) -> LiveBuffer:
    buf = LiveBuffer()
    LIVE[thread_id] = buf
    return buf


def live_snapshot(thread_id: str, after: int = -1) -> dict:
    buf = LIVE.get(thread_id)
    if buf is None:
        return {"running": False, "seq": 0, "elapsed": 0, "changed": False, "segments": []}
    return buf.snapshot(after)


async def run_graph_live(app_graph, inputs, config, thread_id: str):
    """Executa o grafo e devolve o estado final (igual a `ainvoke`), alimentando o buffer ao vivo."""
    if not LIVE_ENABLED:
        return await app_graph.ainvoke(inputs, config=config)
    buf = live_start(thread_id)
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
            except Exception as exc:  # o balão ao vivo nunca pode derrubar a resposta
                print(f"[LIVE] ignorado: {type(exc).__name__}: {exc}")
    finally:
        buf.finish()
    if last is None:
        snapshot = await app_graph.aget_state(config)
        last = snapshot.values
    return last
