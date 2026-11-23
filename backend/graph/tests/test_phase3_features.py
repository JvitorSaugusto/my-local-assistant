import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.controllers.memory_controller import memory_router
from backend.graph import audit_pdf, webkit
from backend.rag import chunker, store_memory
from backend.rag.providers import HeuristicSummarizer
from backend.rag.service import RagService


def _make_memory_store():
    for obj in vars(store_memory).values():
        if isinstance(obj, type) and obj.__module__ == store_memory.__name__:
            if hasattr(obj, "upsert_source") and hasattr(obj, "replace_file_chunks"):
                try:
                    return obj()
                except TypeError:
                    return obj(4)
    raise AssertionError("Classe de store em memória não encontrada em backend.rag.store_memory")


def test_memory_visual_manager_api_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_MEMORY_FILE", str(tmp_path / "user_memory.json"))
    monkeypatch.setenv("ASSISTANT_SETTINGS_FILE", str(tmp_path / "settings.json"))

    app = FastAPI()
    app.include_router(memory_router, prefix="/api/memories")
    client = TestClient(app)

    res = client.get("/api/memories")
    assert res.status_code == 200
    assert res.json()["items"] == []

    created = client.post("/api/memories", json={"text": "Usa Linux Mint no notebook"})
    assert created.status_code == 201
    item_id = created.json()["item"]["id"]

    updated = client.put(f"/api/memories/{item_id}", json={"text": "Usa Linux Mint Cinnamon no notebook"})
    assert updated.status_code == 200
    assert updated.json()["item"]["text"] == "Usa Linux Mint Cinnamon no notebook"

    deleted = client.delete(f"/api/memories/{item_id}")
    assert deleted.status_code == 200
    assert deleted.json()["removed"] is True
    assert client.get("/api/memories").json()["items"] == []


def test_web_fetch_online_pdf_and_youtube_transcript(monkeypatch):
    pdf = audit_pdf._SimplePDF("Manual Teste")
    pdf.heading("Guia Prático de Redes", size=14.0)
    pdf.text("O protocolo TCP garante entrega ordenada e controle de congestionamento.", size=10.0)
    pdf_bytes = pdf.to_bytes()

    monkeypatch.setattr(webkit, "_CACHE", {})

    def fake_http_get_bytes(url, timeout=15, max_bytes=1_500_000, headers=None, data=None, validate=True):
        if url.endswith("manual.pdf"):
            return url, "application/pdf", pdf_bytes, None
        if "youtube.com/watch" in url:
            html = (
                '<html><script>var ytInitialPlayerResponse = {'
                '"videoDetails":{"title":"Aula de FastAPI","author":"Canal Dev"},'
                '"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":['
                '{"baseUrl":"https://www.youtube.com/api/timedtext?v=abc12345678&lang=pt","languageCode":"pt"}'
                ']}}};</script></html>'
            )
            return url, "text/html; charset=utf-8", html.encode("utf-8"), "utf-8"
        if "api/timedtext" in url:
            xml = (
                '<?xml version="1.0" encoding="utf-8"?><transcript>'
                '<text start="0.0" dur="3.5">Olá pessoal, hoje vamos ver FastAPI.</text>'
                '<text start="4.0" dur="4.0">Rotas assíncronas usam async def.</text>'
                '</transcript>'
            )
            return url, "text/xml; charset=utf-8", xml.encode("utf-8"), "utf-8"
        raise OSError("URL inesperada")

    monkeypatch.setattr(webkit, "http_get_bytes", fake_http_get_bytes)

    pdf_out = webkit.fetch_page("https://example.com/manual.pdf", max_chars=4000)
    assert "Guia Prático de Redes" in pdf_out or "protocolo TCP" in pdf_out
    assert "ERRO:" not in pdf_out

    assert webkit.extract_youtube_video_id("https://youtu.be/abc12345678?t=30") == "abc12345678"
    assert webkit.extract_youtube_video_id("https://www.youtube.com/watch?v=abc12345678") == "abc12345678"

    yt_out = webkit.fetch_page("https://www.youtube.com/watch?v=abc12345678", max_chars=4000)
    assert "Aula de FastAPI" in yt_out
    assert "Rotas assíncronas usam async def." in yt_out
    assert "[00:00]" in yt_out


def test_personal_documents_rag_scan_chunk_and_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_DOCS_DIR", str(tmp_path / "rag_docs"))

    pdf = audit_pdf._SimplePDF("Apostila")
    pdf.heading("Capítulo 1: Banco de Dados", size=14.0)
    pdf.text("Índices B-Tree aceleram consultas por intervalo e igualdade no PostgreSQL.", size=10.0)

    docs_payload = [
        ("apostila.pdf", pdf.to_bytes()),
        ("receita.md", b"# Pao Algodao\n\nUse tangzhong e leite de coco.\n\n## Preparo\n\nSove por 10 minutos.\n"),
    ]

    class FakeEmbedder:
        dim = 4

        def embed(self, texts):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    store = _make_memory_store()
    service = RagService(store=store, embedder=FakeEmbedder(), summarizer=HeuristicSummarizer())

    async def _run():
        res = await service.ingest_documents("Estudos Pessoais", docs_payload)
        assert res["source_id"] > 0
        if service._tasks:
            await asyncio.gather(*list(service._tasks))

        status = await service.status(res["source_id"])
        assert status is not None
        assert status["job"]["status"] == "done", status["job"].get("error")

        sources = await service.list_sources()
        assert len(sources) == 1
        assert sources[0]["name"] == "Estudos Pessoais"
        assert sources[0]["files"] == 2
        assert sources[0]["chunks"] >= 2

        hits, _label, used = await service.search_scoped("tangzhong", workspace=None, source="Estudos Pessoais", limit=4)
        assert len(used) == 1
        assert any("receita.md" in h.path for h in hits)

    asyncio.run(_run())

    doc_text = "[página 1]\nIntrodução ao assunto.\n\nSegundo parágrafo importante.\n\n[página 2]\nConclusão final."
    chunks = chunker.chunk_file("guia.pdf", doc_text, "pdf")
    assert len(chunks) >= 2
    assert any("página 1" in c.qualname for c in chunks)
    assert any("página 2" in c.qualname for c in chunks)
