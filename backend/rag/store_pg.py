"""Store em PostgreSQL + pgvector (schema próprio `rag`). Fala SQL puro via SQLAlchemy async (asyncpg).

Os vetores trafegam como texto ('[0.1,0.2,...]') e são convertidos com CAST no SQL; assim não
é preciso registrar tipos do pgvector no driver.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from .entities import SearchHit

_JOB_FIELDS = {"status", "phase", "files_total", "files_done", "chunks_done", "current_file", "error"}
_JOB_DONE = {"done", "failed", "cancelled", "interrupted"}
_SELECT_HIT = "id, path, kind, qualname, start_line, end_line, coalesce(summary, '') AS summary, content"


def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in values) + "]"


def _like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _hits(rows, by: str) -> list[SearchHit]:
    return [
        SearchHit(r.id, r.path, r.kind, r.qualname or "", r.start_line or 0, r.end_line or 0,
                  r.summary or "", r.content, float(getattr(r, "score", 0.0) or 0.0), [by])
        for r in rows
    ]


class PgVectorStore:
    def __init__(self, database_url: str, dim: int) -> None:
        if not database_url:
            raise RuntimeError("DATABASE_URL (ou RAG_DATABASE_URL) não está definida.")
        self.dim = int(dim)
        self.engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)

    # ── schema ───────────────────────────────────────────────────────────
    async def ensure_schema(self) -> None:
        try:
            async with self.engine.begin() as conn:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Não foi possível ativar a extensão pgvector. O Postgres precisa ter o pgvector instalado "
                "(ex.: imagem Docker 'pgvector/pgvector:pg16') e o usuário precisa poder criar extensões. "
                f"Detalhe: {exc}"
            ) from exc

        ddl = [
            "CREATE SCHEMA IF NOT EXISTS rag",
            """CREATE TABLE IF NOT EXISTS rag.sources (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, root_path TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
            """CREATE TABLE IF NOT EXISTS rag.files (
                source_id INT NOT NULL REFERENCES rag.sources(id) ON DELETE CASCADE, path TEXT NOT NULL,
                sha1 TEXT NOT NULL, language TEXT, indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (source_id, path))""",
            f"""CREATE TABLE IF NOT EXISTS rag.chunks (
                id BIGSERIAL PRIMARY KEY,
                source_id INT NOT NULL REFERENCES rag.sources(id) ON DELETE CASCADE,
                path TEXT NOT NULL, language TEXT, kind TEXT NOT NULL, qualname TEXT, parent TEXT,
                start_line INT, end_line INT, part INT NOT NULL DEFAULT 1, parts INT NOT NULL DEFAULT 1,
                content TEXT NOT NULL, content_hash TEXT NOT NULL, summary TEXT, tag TEXT,
                embedding vector({self.dim}),
                tsv tsvector GENERATED ALWAYS AS (
                    to_tsvector('simple', coalesce(qualname, '') || ' ' || coalesce(summary, '') || ' ' || content)
                ) STORED)""",
            "CREATE INDEX IF NOT EXISTS rag_chunks_source_path ON rag.chunks (source_id, path)",
            "CREATE INDEX IF NOT EXISTS rag_chunks_hash ON rag.chunks (content_hash)",
            "CREATE INDEX IF NOT EXISTS rag_chunks_tsv ON rag.chunks USING gin (tsv)",
            """CREATE TABLE IF NOT EXISTS rag.jobs (
                id SERIAL PRIMARY KEY, source_id INT NOT NULL REFERENCES rag.sources(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'queued', phase TEXT NOT NULL DEFAULT '',
                files_total INT NOT NULL DEFAULT 0, files_done INT NOT NULL DEFAULT 0,
                chunks_done INT NOT NULL DEFAULT 0, current_file TEXT NOT NULL DEFAULT '', error TEXT,
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ)""",
            """CREATE TABLE IF NOT EXISTS rag.workspace_links (
                workspace_root TEXT NOT NULL,
                source_id INT NOT NULL REFERENCES rag.sources(id) ON DELETE CASCADE,
                PRIMARY KEY (workspace_root, source_id))""",
        ]
        async with self.engine.begin() as conn:
            for statement in ddl:
                await conn.execute(text(statement))

        async with self.engine.connect() as conn:
            row = (await conn.execute(text(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'rag.chunks'::regclass AND attname = 'embedding'"
            ))).first()
        if row and int(row[0]) not in (-1, self.dim):
            raise RuntimeError(
                f"A tabela rag.chunks foi criada com embedding de {row[0]} dimensões, mas RAG_EMBED_DIM={self.dim}. "
                "Use o mesmo modelo de embedding ou recrie o schema (DROP SCHEMA rag CASCADE)."
            )

        try:  # índice aproximado é opcional: sem ele a busca vetorial é exata (mais lenta)
            async with self.engine.begin() as conn:
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS rag_chunks_embedding ON rag.chunks USING hnsw (embedding vector_cosine_ops)"
                ))
        except Exception as exc:  # noqa: BLE001
            print(f"ℹ️ [RAG] índice HNSW não criado (busca vetorial exata): {exc}")

    # ── fontes ───────────────────────────────────────────────────────────
    async def upsert_source(self, name, kind, root_path):
        async with self.engine.begin() as conn:
            row = (await conn.execute(text(
                """INSERT INTO rag.sources (name, kind, root_path) VALUES (:n, :k, :r)
                   ON CONFLICT (name) DO UPDATE SET kind = EXCLUDED.kind, root_path = EXCLUDED.root_path, updated_at = now()
                   RETURNING id"""), {"n": name, "k": kind, "r": root_path})).first()
        return int(row[0])

    async def find_source(self, name=None, root_path=None):
        if not name and not root_path:
            return None
        clause, params = ("name = :v", {"v": name}) if name else ("root_path = :v", {"v": root_path})
        async with self.engine.connect() as conn:
            row = (await conn.execute(text(f"SELECT * FROM rag.sources WHERE {clause} LIMIT 1"), params)).first()
        return dict(row._mapping) if row else None

    async def list_sources(self):
        sql = """SELECT s.*, (SELECT count(*) FROM rag.files f WHERE f.source_id = s.id) AS files,
                        (SELECT count(*) FROM rag.chunks c WHERE c.source_id = s.id) AS chunks
                 FROM rag.sources s ORDER BY s.name"""
        async with self.engine.connect() as conn:
            return [dict(r._mapping) for r in (await conn.execute(text(sql))).all()]

    async def delete_source(self, source_id):
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag.sources WHERE id = :i"), {"i": source_id})

    # ── arquivos e chunks ────────────────────────────────────────────────
    async def file_hashes(self, source_id):
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text("SELECT path, sha1 FROM rag.files WHERE source_id = :s"), {"s": source_id})).all()
        return {r[0]: r[1] for r in rows}

    async def delete_files(self, source_id, paths):
        if not paths:
            return
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag.chunks WHERE source_id = :s AND path = ANY(:p)"), {"s": source_id, "p": list(paths)})
            await conn.execute(text("DELETE FROM rag.files WHERE source_id = :s AND path = ANY(:p)"), {"s": source_id, "p": list(paths)})

    async def get_summaries(self, hashes):
        if not hashes:
            return {}
        sql = """SELECT DISTINCT ON (content_hash) content_hash, summary FROM rag.chunks
                 WHERE content_hash = ANY(:h) AND summary IS NOT NULL AND summary <> ''"""
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(sql), {"h": list(set(hashes))})).all()
        return {r[0]: r[1] for r in rows}

    async def replace_file_chunks(self, source_id, path, sha1, language, rows):
        insert = text(
            """INSERT INTO rag.chunks (source_id, path, language, kind, qualname, parent, start_line, end_line,
                   part, parts, content, content_hash, summary, tag, embedding)
               VALUES (:source_id, :path, :language, :kind, :qualname, :parent, :start_line, :end_line,
                   :part, :parts, :content, :content_hash, :summary, :tag, CAST(CAST(:embedding AS text) AS vector))"""
        )
        params = []
        for row in rows:
            item = dict(row)
            item["source_id"] = source_id
            item["content"] = item["content"].replace("\x00", "")
            item["embedding"] = _vec(item["embedding"])
            params.append(item)
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag.chunks WHERE source_id = :s AND path = :p"), {"s": source_id, "p": path})
            if params:
                await conn.execute(insert, params)
            await conn.execute(text(
                """INSERT INTO rag.files (source_id, path, sha1, language) VALUES (:s, :p, :h, :l)
                   ON CONFLICT (source_id, path) DO UPDATE SET sha1 = EXCLUDED.sha1, language = EXCLUDED.language, indexed_at = now()"""),
                {"s": source_id, "p": path, "h": sha1, "l": language})
            await conn.execute(text("UPDATE rag.sources SET updated_at = now() WHERE id = :s"), {"s": source_id})

    async def outline(self, source_id):
        sql = """SELECT path, kind, qualname, parent, start_line, end_line, summary, part
                 FROM rag.chunks WHERE source_id = :s ORDER BY path, start_line"""
        async with self.engine.connect() as conn:
            return [dict(r._mapping) for r in (await conn.execute(text(sql), {"s": source_id})).all()]

    # ── busca ────────────────────────────────────────────────────────────
    @staticmethod
    def _scope(source_ids, path_prefix) -> tuple[str, dict]:
        clause = "source_id = ANY(:sids)"
        params: dict = {"sids": list(source_ids)}
        if path_prefix:
            clause += " AND path LIKE :pfx"
            params["pfx"] = _like(path_prefix) + "%"
        return clause, params

    async def search_vector(self, source_ids, embedding, limit, path_prefix):
        clause, params = self._scope(source_ids, path_prefix)
        params.update(q=_vec(embedding), lim=int(limit))
        sql = f"""SELECT {_SELECT_HIT}, 1 - (embedding <=> CAST(CAST(:q AS text) AS vector)) AS score
                  FROM rag.chunks WHERE {clause} AND embedding IS NOT NULL
                  ORDER BY embedding <=> CAST(CAST(:q AS text) AS vector) LIMIT :lim"""
        async with self.engine.connect() as conn:
            return _hits((await conn.execute(text(sql), params)).all(), "vetor")

    async def search_text(self, source_ids, tokens, limit, path_prefix):
        words = [t for t in tokens if t.isalnum()]
        if not words:
            return []
        clause, params = self._scope(source_ids, path_prefix)
        params.update(tsq=" | ".join(words), lim=int(limit))
        sql = f"""SELECT {_SELECT_HIT}, ts_rank(tsv, to_tsquery('simple', :tsq)) AS score
                  FROM rag.chunks WHERE {clause} AND tsv @@ to_tsquery('simple', :tsq)
                  ORDER BY score DESC LIMIT :lim"""
        async with self.engine.connect() as conn:
            return _hits((await conn.execute(text(sql), params)).all(), "texto")

    async def search_symbol(self, source_ids, tokens, limit, path_prefix):
        if not tokens:
            return []
        clause, params = self._scope(source_ids, path_prefix)
        ors = []
        for i, token in enumerate(tokens):
            params[f"t{i}"] = "%" + _like(token) + "%"
            ors.append(f"qualname ILIKE :t{i} OR path ILIKE :t{i}")
        params["lim"] = int(limit)
        sql = f"""SELECT {_SELECT_HIT}, 1.0 AS score FROM rag.chunks
                  WHERE {clause} AND ({' OR '.join(ors)})
                  ORDER BY length(coalesce(qualname, path)) ASC, id LIMIT :lim"""
        async with self.engine.connect() as conn:
            return _hits((await conn.execute(text(sql), params)).all(), "símbolo")

    # ── jobs ─────────────────────────────────────────────────────────────
    async def create_job(self, source_id):
        async with self.engine.begin() as conn:
            row = (await conn.execute(text("INSERT INTO rag.jobs (source_id) VALUES (:s) RETURNING id"), {"s": source_id})).first()
        return int(row[0])

    async def update_job(self, job_id, **fields):
        sets = [f"{k} = :{k}" for k in fields if k in _JOB_FIELDS]
        params = {k: v for k, v in fields.items() if k in _JOB_FIELDS}
        if fields.get("status") in _JOB_DONE:
            sets.append("finished_at = now()")
        if not sets:
            return
        params["id"] = job_id
        async with self.engine.begin() as conn:
            await conn.execute(text(f"UPDATE rag.jobs SET {', '.join(sets)} WHERE id = :id"), params)

    async def get_job(self, job_id):
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT * FROM rag.jobs WHERE id = :i"), {"i": job_id})).first()
        return dict(row._mapping) if row else None

    async def latest_job(self, source_id):
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT * FROM rag.jobs WHERE source_id = :s ORDER BY id DESC LIMIT 1"), {"s": source_id})).first()
        return dict(row._mapping) if row else None

    async def fail_stale_jobs(self):
        async with self.engine.begin() as conn:
            result = await conn.execute(text(
                """UPDATE rag.jobs SET status = 'interrupted', finished_at = now(),
                          error = 'Servidor reiniciado durante a ingestão.'
                   WHERE status IN ('queued', 'running')"""))
        return result.rowcount or 0


    async def set_workspace_links(self, root, source_ids):
        ids = list(dict.fromkeys(int(i) for i in source_ids))
        async with self.engine.begin() as conn:
            await conn.execute(text("DELETE FROM rag.workspace_links WHERE workspace_root = :r"), {"r": root})
            if ids:
                await conn.execute(
                    text("INSERT INTO rag.workspace_links (workspace_root, source_id) VALUES (:r, :s) ON CONFLICT DO NOTHING"),
                    [{"r": root, "s": i} for i in ids],
                )

    async def get_workspace_links(self, root):
        sql = "SELECT source_id FROM rag.workspace_links WHERE workspace_root = :r ORDER BY source_id"
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(sql), {"r": root})).all()
        return [r[0] for r in rows]
