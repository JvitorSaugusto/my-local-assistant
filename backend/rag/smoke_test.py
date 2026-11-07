"""Teste de fumaça com Postgres + Ollama REAIS. Na raiz do projeto:

    python -m backend.rag.smoke_test [pasta]

Indexa a pasta (padrão: backend/), faz uma busca, mostra o mapa e apaga a fonte de teste.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


async def main() -> int:
    load_dotenv()
    from .service import RagService

    target = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
    service = RagService()
    print(f"1) schema/pgvector… (embedding: {service.cfg.embed_model}, dim {service.cfg.embed_dim})")
    await service.startup()
    print("   ok")

    print(f"2) indexando {target}")
    started = await service.ingest_workspace(str(target), name="__smoke_test__", force=True)
    while True:
        info = await service.status(started["source_id"])
        job = info["job"] if info else None
        if not job:
            await asyncio.sleep(1)
            continue
        print(f"   {job['status']:<9} {job['files_done']}/{job['files_total']} arquivos, {job['chunks_done']} chunks  {job['current_file']}")
        if job["status"] in {"done", "failed", "cancelled", "interrupted"}:
            break
        await asyncio.sleep(2)
    if job["status"] != "done":
        print("FALHOU:", job.get("error"))
        return 1

    print("3) busca")
    for hit in await service.search("como as tarefas são executadas", source_id=started["source_id"], limit=3):
        print(f"   {hit.path}:{hit.start_line}-{hit.end_line} {hit.qualname}  [{', '.join(hit.matched_by)}]")

    print("4) mapa (primeiras linhas)")
    print("\n".join((await service.repo_map(started["source_id"])).splitlines()[:12]))

    await service.delete_source(started["source_id"])
    print("5) fonte de teste removida. TUDO OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
