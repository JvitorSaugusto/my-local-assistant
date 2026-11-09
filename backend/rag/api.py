"""Router FastAPI do RAG (/api/rag). Só traduz HTTP para chamadas do RagService."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .service import RagUnavailable, get_service, new_upload_path
from .zip_utils import ZipRejected

rag_router = APIRouter()


class WorkspaceIngestRequest(BaseModel):
    path: str = Field(min_length=1)
    name: str | None = None
    force: bool = False


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    source_id: int | None = None
    limit: int = Field(default=8, ge=1, le=30)
    path_prefix: str | None = None


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, RagUnavailable):
        return HTTPException(status_code=503, detail=f"RAG indisponível: {exc}")
    if isinstance(exc, (ValueError, ZipRejected)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Erro no RAG: {exc}")


@rag_router.get("/sources")
async def list_sources():
    try:
        return await get_service().list_sources(True)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc


@rag_router.post("/sources/workspace", status_code=202)
async def ingest_workspace(payload: WorkspaceIngestRequest):
    try:
        return await get_service().ingest_workspace(payload.path, payload.name, payload.force)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc


@rag_router.post("/sources/zip", status_code=202)
async def ingest_zip(file: UploadFile = File(...), name: str = Form(""), force: bool = Form(False)):
    service = get_service()
    limit = service.cfg.zip_max_bytes
    path = new_upload_path(service.cfg.work_dir)
    written = 0
    try:
        with open(path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ValueError("Arquivo zip acima do limite permitido.")
                out.write(chunk)
        stem = (file.filename or "upload").rsplit(".", 1)[0]
        return await service.ingest_zip(path, name or stem, force)
    except Exception as exc:  # noqa: BLE001
        from pathlib import Path

        Path(path).unlink(missing_ok=True)
        raise _http(exc) from exc


@rag_router.get("/sources/{source_id}")
async def source_status(source_id: int):
    try:
        result = await get_service().status(source_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Fonte não encontrada")
    return result


@rag_router.delete("/sources/{source_id}")
async def delete_source(source_id: int):
    try:
        await get_service().delete_source(source_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc
    return {"deleted": source_id}


@rag_router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: int):
    try:
        ok = await get_service().cancel(job_id)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Nenhuma ingestão ativa com esse id.")
    return {"cancelling": job_id}


@rag_router.get("/sources/{source_id}/map")
async def source_map(source_id: int):
    try:
        return {"map": await get_service().repo_map(source_id)}
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc


@rag_router.post("/search")
async def search(payload: SearchRequest):
    try:
        hits = await get_service().search(payload.query, payload.source_id, None, payload.limit, payload.path_prefix)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc
    return [
        {"path": h.path, "kind": h.kind, "qualname": h.qualname, "start_line": h.start_line, "end_line": h.end_line,
         "summary": h.summary, "content": h.content, "score": round(h.score, 5), "matched_by": h.matched_by}
        for h in hits
    ]



class LinksRequest(BaseModel):
    path: str = Field(min_length=1)
    source_ids: list[int] = Field(default_factory=list)


@rag_router.get("/links")
async def get_links(path: str):
    try:
        return {"source_ids": await get_service().get_links(path)}
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc


@rag_router.put("/links")
async def put_links(payload: LinksRequest):
    try:
        return {"source_ids": await get_service().set_links(payload.path, payload.source_ids)}
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc



@rag_router.get("/scope")
async def scope(path: str = ""):
    """Fonte do projeto + vínculos + todas as fontes (alimenta o seletor de fontes do chat)."""
    try:
        return await get_service().scope_info(path)
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc



@rag_router.get("/summarizer")
async def summarizer_info():
    """Qual resumidor está ativo (IA ou heurístico), modelo e parâmetros."""
    try:
        return await get_service().summarizer_info()
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc


@rag_router.post("/summarizer/test")
async def summarizer_test():
    """Teste ao vivo da IA de resumos (pode levar alguns segundos)."""
    try:
        return await get_service().test_summarizer()
    except Exception as exc:  # noqa: BLE001
        raise _http(exc) from exc
