"""Store em memória: mesma interface do Postgres. Usado em testes e como referência de comportamento."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .entities import SearchHit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class MemoryStore:
    def __init__(self) -> None:
        self.sources: dict[int, dict] = {}
        self.files: dict[tuple[int, str], dict] = {}
        self.chunks: list[dict] = []
        self.jobs: dict[int, dict] = {}
        self.links: dict[str, list[int]] = {}
        self._next_source = 1
        self._next_chunk = 1
        self._next_job = 1

    async def ensure_schema(self) -> None:
        return None

    async def upsert_source(self, name, kind, root_path):
        for sid, s in self.sources.items():
            if s["name"] == name:
                s.update(kind=kind, root_path=root_path, updated_at=_now())
                return sid
        sid = self._next_source
        self._next_source += 1
        self.sources[sid] = {"id": sid, "name": name, "kind": kind, "root_path": root_path,
                             "created_at": _now(), "updated_at": _now()}
        return sid

    async def find_source(self, name=None, root_path=None):
        for s in self.sources.values():
            if (name and s["name"] == name) or (root_path and s["root_path"] == root_path):
                return dict(s)
        return None

    async def list_sources(self):
        out = []
        for s in self.sources.values():
            files = sum(1 for (sid, _p) in self.files if sid == s["id"])
            chunks = sum(1 for c in self.chunks if c["source_id"] == s["id"])
            out.append({**s, "files": files, "chunks": chunks})
        return out

    async def delete_source(self, source_id):
        self.sources.pop(source_id, None)
        self.files = {k: v for k, v in self.files.items() if k[0] != source_id}
        self.chunks = [c for c in self.chunks if c["source_id"] != source_id]
        self.jobs = {k: v for k, v in self.jobs.items() if v["source_id"] != source_id}
        self.links = {r: [i for i in ids if i != source_id] for r, ids in self.links.items()}

    async def file_hashes(self, source_id):
        return {p: f["sha1"] for (sid, p), f in self.files.items() if sid == source_id}

    async def delete_files(self, source_id, paths):
        for p in paths:
            self.files.pop((source_id, p), None)
        self.chunks = [c for c in self.chunks if not (c["source_id"] == source_id and c["path"] in set(paths))]

    async def get_summaries(self, hashes):
        wanted = set(hashes)
        return {c["content_hash"]: c["summary"] for c in self.chunks if c["content_hash"] in wanted and c.get("summary")}

    async def replace_file_chunks(self, source_id, path, sha1, language, rows):
        self.chunks = [c for c in self.chunks if not (c["source_id"] == source_id and c["path"] == path)]
        for row in rows:
            self.chunks.append({**row, "id": self._next_chunk, "source_id": source_id})
            self._next_chunk += 1
        self.files[(source_id, path)] = {"sha1": sha1, "language": language}

    async def outline(self, source_id):
        keys = ("path", "kind", "qualname", "parent", "start_line", "end_line", "summary", "part")
        return [{k: c.get(k) for k in keys} for c in self.chunks if c["source_id"] == source_id]

    def _hit(self, c, score, by):
        return SearchHit(c["id"], c["path"], c["kind"], c["qualname"], c["start_line"], c["end_line"],
                         c.get("summary", ""), c["content"], score, [by])

    def _pool(self, source_ids, path_prefix):
        return [c for c in self.chunks if c["source_id"] in source_ids and (not path_prefix or c["path"].startswith(path_prefix))]

    async def search_vector(self, source_ids, embedding, limit, path_prefix):
        scored = [(_cos(embedding, c["embedding"]), c) for c in self._pool(source_ids, path_prefix)]
        scored.sort(key=lambda t: -t[0])
        return [self._hit(c, s, "vetor") for s, c in scored[:limit]]

    async def search_text(self, source_ids, tokens, limit, path_prefix):
        out = []
        for c in self._pool(source_ids, path_prefix):
            hay = f"{c['qualname']} {c.get('summary','')} {c['content']}".lower()
            score = sum(hay.count(t.lower()) for t in tokens)
            if score:
                out.append((score, c))
        out.sort(key=lambda t: -t[0])
        return [self._hit(c, float(s), "texto") for s, c in out[:limit]]

    async def search_symbol(self, source_ids, tokens, limit, path_prefix):
        out = []
        for c in self._pool(source_ids, path_prefix):
            target = f"{c['qualname']} {c['path']}".lower()
            if any(t.lower() in target for t in tokens):
                out.append((len(c["qualname"] or c["path"]), c))
        out.sort(key=lambda t: t[0])
        return [self._hit(c, 1.0, "símbolo") for _l, c in out[:limit]]

    async def create_job(self, source_id):
        jid = self._next_job
        self._next_job += 1
        self.jobs[jid] = {"id": jid, "source_id": source_id, "status": "queued", "phase": "", "files_total": 0,
                          "files_done": 0, "chunks_done": 0, "current_file": "", "error": None,
                          "started_at": _now(), "finished_at": None}
        return jid

    async def update_job(self, job_id, **fields):
        if job_id in self.jobs:
            self.jobs[job_id].update(fields)

    async def get_job(self, job_id):
        j = self.jobs.get(job_id)
        return dict(j) if j else None

    async def latest_job(self, source_id):
        js = [j for j in self.jobs.values() if j["source_id"] == source_id]
        return dict(max(js, key=lambda j: j["id"])) if js else None

    async def fail_stale_jobs(self):
        n = 0
        for j in self.jobs.values():
            if j["status"] in {"queued", "running"}:
                j.update(status="interrupted", error="Servidor reiniciado durante a ingestão.", finished_at=_now())
                n += 1
        return n


    async def set_workspace_links(self, root, source_ids):
        self.links[root] = list(dict.fromkeys(int(i) for i in source_ids))

    async def get_workspace_links(self, root):
        return list(self.links.get(root, []))
