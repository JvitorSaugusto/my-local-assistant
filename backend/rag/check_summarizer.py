"""Diagnóstico do resumidor por IA. Na raiz do projeto:

    python -m backend.rag.check_summarizer

Mostra a configuração, faz uma chamada CRUA ao Ollama (para ver se a resposta vem vazia e quantos
tokens foram gastos pensando) e testa o OllamaSummarizer de verdade, dizendo se a IA funcionou.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

from dotenv import load_dotenv

SAMPLE = (
    "def somar_total(itens, taxa):\n"
    '    """Soma os itens e aplica a taxa."""\n'
    "    total = sum(i.valor for i in itens)\n"
    "    return round(total * (1 + taxa), 2)\n"
)


def main() -> int:
    load_dotenv()
    from .chunker import chunk_file
    from .config import load_config
    from .providers import OllamaSummarizer, _post_json

    cfg = load_config()
    print(f"Ollama: {cfg.ollama_url}")
    print(f"RAG_SUMMARY_MODEL: {cfg.summary_model or '(vazio -> só resumo heurístico, sem IA)'}")
    if not cfg.summary_model:
        print("\nDefina RAG_SUMMARY_MODEL no .env e reinicie o servidor para usar IA nos resumos.")
        return 1

    summarizer = OllamaSummarizer(cfg.ollama_url, cfg.summary_model, cfg.summary_timeout, cfg.summary_think)
    print(f"think: {summarizer.think!r} | timeout: {cfg.summary_timeout}s | paralelismo: {cfg.summary_concurrency}")

    print("\n0) Modelos instalados no Ollama (/api/tags)...")
    try:
        with urllib.request.urlopen(f"{cfg.ollama_url}/api/tags", timeout=10) as resp:
            installed = [m.get("name", "") for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
    except Exception as exc:
        print(f"   FALHOU ao listar modelos em {cfg.ollama_url}: {exc}")
        return 1
    print("   " + (", ".join(installed) or "(nenhum modelo instalado)"))
    if cfg.summary_model not in installed and f"{cfg.summary_model}:latest" not in installed:
        print(f"   -> '{cfg.summary_model}' NAO esta instalado. Rode: ollama pull {cfg.summary_model}")
        return 1

    print("\n1) Chamada crua ao Ollama...")
    payload = {"model": cfg.summary_model, "prompt": "Responda apenas: ok", "stream": False,
               "options": {"temperature": 0.1, "num_predict": 512}}
    if summarizer.think is not None:
        payload["think"] = summarizer.think
    started = time.time()
    try:
        body = _post_json(f"{cfg.ollama_url}/api/generate", payload, cfg.summary_timeout, retries=0)
    except RuntimeError as exc:
        print(f"   FALHOU: {exc}")
        return 1
    print(
        f"   {time.time() - started:.1f}s | resposta: {len(str(body.get('response', '')))} caracteres | "
        f"pensamento: {len(str(body.get('thinking', '')))} caracteres | done_reason: {body.get('done_reason')} | "
        f"tokens gerados: {body.get('eval_count')}"
    )
    if not str(body.get("response", "")).strip():
        print(
            "   -> A resposta veio VAZIA. Em modelos de raciocínio isso é o limite de tokens gasto pensando: "
            "use RAG_SUMMARY_THINK=low ou um modelo sem raciocínio."
        )

    print("\n2) Resumo de um trecho de exemplo...")
    chunk = chunk_file("exemplo.py", SAMPLE, "python")[0]
    started = time.time()
    result = summarizer.summarize(chunk)
    print(f"   {time.time() - started:.1f}s | tipo: {result.kind}\n   resumo: {result}")
    if result.kind.startswith("llm:"):
        print("\nOK: a IA está escrevendo os resumos.")
        return 0
    print(f"\nA IA NÃO foi usada (caiu no heurístico). Motivo: {summarizer.last_error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
