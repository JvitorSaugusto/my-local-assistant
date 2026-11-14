"""Núcleo do assistente de git e pacotes do chat (sem LLM, testável com repositórios temporários)."""
from __future__ import annotations

import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

OPS_NAME = "Qwen3-Coder (Ops)"
PROTECTED_BRANCHES = {"main", "master"}
_STOP = set(
    "para como esse essa isso este esta aqui onde quando quero preciso problema erro bug fazer faz mais muito "
    "com sem uma uns umas dos das nos nas que por pelo pela the and not with from this that have gera gere".split()
)
_BAD_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf", ".zip", ".rar", ".lock", ".pyc", ".woff", ".woff2")

_TAG = re.compile(r"^\s*@(ops|commit|pack|primer|zip)(?!\S)[:\s]", re.I)
_OTHER_TAG = re.compile(r"(?<!\S)@(heavy|enhance|generate)(?!\S)", re.I)
_COMMIT_VERB = re.compile(
    r"\b(commita|commite|commitar|comitar|comita|comite|fa[çc]a?\s+(um\s+)?commit|faz(er)?\s+(um\s+)?commit"
    r"|d[êe]\s+(um\s+)?commit|(quero|preciso)\s+(de\s+)?(um\s+)?commit)\b",
    re.I,
)
_QUESTION_START = re.compile(r"^\s*(como|o que|por que|porque|qual|quais|onde|quando)\b", re.I)
_PACK_WHAT = re.compile(r"\b(md|markdown|\.md|pacote|primer)\b", re.I)
_PACK_TO = re.compile(r"\b(claude|ia externa|outra ia|chatgpt|gpt)\b", re.I)
_PACK_VERB = re.compile(r"\b(gera|gere|gerar|monta|monte|montar|cria|crie|criar|prepara|prepare|faz|fa[çc]a|manda|quero|preciso|me d[áa])\b", re.I)
# Resposta curta a uma pergunta do Ops: "todos", "2,7,8", "grupo 2 - a.py, b.py", "sim"...
_SELECTION = re.compile(
    r"^\s*(?:(?:todos|todas|tudo|sim|ok|isso|pode|manda|n[ãa]o|nenhum|cancela\w*)\b|grupos?\s*\d|\d+(?:\s*(?:,|e|-)\s*\d+)*\s*$)",
    re.I,
)
_ASKS_CHOICE = re.compile(r"responda com|quais (?:grupos|arquivos)|me diga|escolha|indique", re.I)
_ZIP_WORD = re.compile(r"\b(zip\w*|compact(?:a|e|ar)\w*|empacot\w*)\b", re.I)
_DELIVER_VERB = re.compile(r"\b(entreg\w+|devolv\w+|baix\w+|me\s+(?:mand|envi)\w+)\b", re.I)
_FILES_NOUN = re.compile(r"\b(arquivos?|pastas?|diret[óo]rios?)\b", re.I)


def _wants_zip(text):
    # True se o usuário pede para receber arquivos ou pastas do projeto (em zip) no chat.
    text = text or ""
    if (_QUESTION_START.match(text) and "?" in text) or re.search(r"#\d+|autocommit", text, re.I):
        return False
    if _COMMIT_VERB.search(text):
        return False
    has_files = bool(_FILES_NOUN.search(text))
    has_deliver = bool(_DELIVER_VERB.search(text))
    if _ZIP_WORD.search(text):
        return has_files or has_deliver
    return has_files and has_deliver


def _ops_awaits_answer(content):
    """True se a última mensagem do Ops ficou esperando uma resposta do usuário."""
    full = str(content or "")
    return "?" in full[-300:] or bool(_ASKS_CHOICE.search(full))


def detect_ops_intent(text, messages):
    """Texto (sem a tag) se a mensagem é para o assistente de git/pacotes; None caso contrário."""
    text = text or ""
    if _OTHER_TAG.search(text[:80]) or "@generate" in text.lower():
        return None
    match = _TAG.match(text)
    if match:
        return text[match.end():].strip() or "o que você pode fazer?"
    previous = None
    for msg in reversed(list(messages or [])[:-1]):
        kind = getattr(msg, "type", "")
        if kind == "tool" or (kind == "ai" and getattr(msg, "tool_calls", None)):
            continue
        previous = msg
        break
    if previous is not None and getattr(previous, "type", "") == "ai" and getattr(previous, "name", None) == OPS_NAME:
        # Antes só continuava no Ops se o fim da mensagem tivesse "?". A lista de grupos termina num aviso,
        # sem "?", então o "todos" seguinte caía no CODE (GPT-OSS), que nunca commitou nada.
        if _ops_awaits_answer(previous.content) or _SELECTION.match(text):
            return text
    if re.match(r"\s*@\w+", text):
        return None
    if _wants_zip(text):
        return text
    low = text.lower()
    if "autocommit" in low or re.search(r"#\d+", text) or "task" in low:
        return None
    if _QUESTION_START.match(text) and "?" in text:
        return None
    if _COMMIT_VERB.search(text):
        return text
    if _PACK_WHAT.search(text) and _PACK_TO.search(text) and _PACK_VERB.search(text):
        return text
    if re.search(r"\bprimer\b", low) and _PACK_VERB.search(text):
        return text
    return None


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), "-c", "core.quotepath=false", *args],
        capture_output=True,
        timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _out(done):
    return (done.stdout or b"").decode("utf-8", errors="replace").strip()


def is_secret_path(path):
    low = str(path).replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    if name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template"))):
        return True
    return name.endswith((".pem", ".key", ".p12", ".pfx")) or name.startswith("id_rsa") or "secret" in name


def current_branch(root):
    return _out(_git(root, "rev-parse", "--abbrev-ref", "HEAD"))


def is_repo(root):
    return _git(root, "rev-parse", "--show-toplevel").returncode == 0


def _count_lines(path):
    try:
        data = path.read_bytes()[:1_000_000]
    except OSError:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def git_changes(root):
    """Arquivos com alterações não commitadas: [{path, status, staged, added, removed}]."""
    root = Path(root)
    done = _git(root, "status", "--porcelain=v1", "-z", "-uall")
    if done.returncode != 0:
        raise RuntimeError("Não é um repositório git.")
    entries = (done.stdout or b"").decode("utf-8", errors="replace").split("\0")
    items, index = [], 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            index += 1  # o nome antigo vem no próximo campo
        if code == "??":
            status = "novo"
        elif "D" in code:
            status = "removido"
        elif code[0] in "RC":
            status = "renomeado"
        elif "A" in code:
            status = "adicionado"
        else:
            status = "modificado"
        items.append({"path": path, "status": status, "staged": code[0] not in " ?", "added": 0, "removed": 0})
    stats = {}
    numstat = _git(root, "diff", "HEAD", "--numstat")
    for line in _out(numstat).splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            stats[parts[2]] = (int(parts[0]), int(parts[1]))
    for item in items:
        if item["status"] == "novo":
            item["added"] = _count_lines(root / item["path"])
        elif item["path"] in stats:
            item["added"], item["removed"] = stats[item["path"]]
    return items


def format_changes(items, branch="", limit=60):
    if not items:
        return "Nenhum arquivo com alterações não commitadas."
    head = f"{len(items)} arquivo(s) com alterações não commitadas" + (f" na branch '{branch}':" if branch else ":")
    lines = [
        f"- {i['path']} ({i['status']}{', no stage' if i['staged'] else ''}, +{i['added']} -{i['removed']})"
        for i in items[:limit]
    ]
    if len(items) > limit:
        lines.append(f"... e mais {len(items) - limit}")
    return head + "\n" + "\n".join(lines)


def resolve_names(candidates, names):
    """Casa nomes dados pelo usuário (caminho, nome do arquivo ou sufixo) com candidates.
    Devolve (resolvidos, ambíguos{nome: [opções]}, ausentes)."""
    pool = list(candidates)
    found, ambiguous, missing = [], {}, []
    for raw in names or []:
        name = str(raw).strip().replace("\\", "/").strip("'\"")
        if not name:
            continue
        exact = [c for c in pool if c == name]
        hits = exact or [c for c in pool if c.rsplit("/", 1)[-1] == name] or [c for c in pool if c.endswith("/" + name)]
        if len(hits) == 1:
            if hits[0] not in found:
                found.append(hits[0])
        elif len(hits) > 1:
            ambiguous[name] = hits[:6]
        else:
            missing.append(name)
    return found, ambiguous, missing


def _problems_text(ambiguous, missing):
    parts = []
    if ambiguous:
        parts.append("; ".join(f"'{n}' bate com {', '.join(o)}" for n, o in ambiguous.items()))
    if missing:
        parts.append("não encontrei: " + ", ".join(missing))
    return "ERRO: " + " | ".join(parts) + ". Peça ao usuário o caminho completo."


def diff_text(root, paths, per_file=5000, total=18000):
    root = Path(root)
    changes = {i["path"]: i for i in git_changes(root)}
    found, ambiguous, missing = resolve_names(changes.keys(), paths)
    if ambiguous or missing:
        return _problems_text(ambiguous, missing)
    chunks, used = [], 0
    for path in found:
        if is_secret_path(path):
            body = "(conteúdo omitido: parece arquivo de segredo)"
        elif changes[path]["status"] == "novo":
            try:
                text = (root / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            body = "(arquivo novo)\n" + "\n".join(text.splitlines()[:80])
        else:
            body = _out(_git(root, "diff", "HEAD", "--", path)) or "(sem diff de conteúdo)"
        if len(body) > per_file:
            body = body[:per_file] + "\n[... diff truncado ...]"
        if used + len(body) > total:
            chunks.append(f"=== {path} === (omitido: limite de tamanho; peça este arquivo sozinho)")
            continue
        used += len(body)
        chunks.append(f"=== {path} ({changes[path]['status']}) ===\n{body}")
    return "\n\n".join(chunks) or "Nada para mostrar."


def commit_paths(root, paths, message):
    root = Path(root)
    message = str(message or "").strip()
    if not message:
        return "ERRO: escreva a mensagem do commit."
    if not is_repo(root):
        return "ERRO: não é um repositório git."
    branch = current_branch(root)
    if branch in PROTECTED_BRANCHES:
        return f"ERRO: você está na branch protegida '{branch}'. Troque para uma branch de trabalho antes."
    changes = {i["path"]: i for i in git_changes(root)}
    found, ambiguous, missing = resolve_names(changes.keys(), paths)
    if ambiguous or missing:
        return _problems_text(ambiguous, missing)
    if not found:
        return "ERRO: nenhum arquivo informado."
    secrets = [p for p in found if is_secret_path(p)]
    if secrets:
        return "ERRO: não commito arquivos que parecem segredos: " + ", ".join(secrets)
    for path in found:
        if _git(root, "add", "--", path).returncode != 0:
            return f"ERRO: não consegui adicionar '{path}' (talvez esteja no .gitignore)."
    done = _git(root, "commit", "-q", "-m", message[:500], "--", *found)
    if done.returncode != 0:
        detail = (_out(done) or (done.stderr or b"").decode("utf-8", errors="replace").strip())[-300:]
        return f"ERRO ao commitar: {detail}"
    short = _out(_git(root, "rev-parse", "--short", "HEAD"))
    return (
        f"Commit {short} em '{branch}' com {len(found)} arquivo(s): {', '.join(found)}. "
        "Para desfazer: git reset --soft HEAD~1"
    )


def suggest_files(root, problem, extra_paths=None, limit=8):
    """Arquivos mais prováveis para um problema: nome, trechos (git grep) e alterações recentes. [(path, motivo)]"""
    root = Path(root)
    tokens = []
    for word in re.findall(r"[A-Za-zÀ-ÿ_][\w]{3,}", (problem or "").lower()):
        if word not in _STOP and word not in tokens:
            tokens.append(word)
    tokens = tokens[:8]
    tracked = [p for p in _out(_git(root, "ls-files")).splitlines() if p and not p.lower().endswith(_BAD_EXT)]
    score, why = {}, {}

    def add(path, points, reason):
        score[path] = score.get(path, 0) + points
        if reason not in why.setdefault(path, []):
            why[path].append(reason)

    for path in extra_paths or []:
        add(path, 4, "achado pela busca semântica")
    for path in tracked:
        low = path.lower()
        base = low.rsplit("/", 1)[-1]
        for token in tokens:
            if token in base:
                add(path, 3, f"nome contém '{token}'")
            elif token in low:
                add(path, 1.5, f"pasta contém '{token}'")
    for token in tokens:
        done = _git(root, "grep", "-i", "-c", "-F", "-e", token)
        for line in _out(done).splitlines()[:400]:
            path, _sep, count = line.rpartition(":")
            if path in tracked and count.isdigit():
                add(path, min(int(count), 6) * 0.5, f"cita '{token}' ({count}x)")
    try:
        for item in git_changes(root):
            if item["path"] in score or any(t in item["path"].lower() for t in tokens):
                add(item["path"], 2, "alterado e ainda não commitado")
    except RuntimeError:
        pass
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [(path, "; ".join(why[path][:3])) for path, _pts in ranked]


def resolve_project_files(root, names):
    tracked = _out(_git(Path(root), "ls-files")).splitlines()
    return resolve_names(tracked, names)


def pack_dir():
    raw = os.getenv("TASK_PACK_DIR")
    base = Path(raw) if raw else Path.home() / ".assistente_local" / "packs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_pack(markdown, hint=""):
    base = pack_dir()
    now = time.time()
    for old in base.glob("pacote_*.md"):
        try:
            if now - old.stat().st_mtime > 30 * 24 * 3600:
                old.unlink()
        except OSError:
            continue
    slug = re.sub(r"[^a-z0-9]+", "-", str(hint).lower())[:40].strip("-") or "contexto"
    path = base / f"pacote_{time.strftime('%Y%m%d_%H%M%S')}_{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def pack_file_path(name):
    if not re.fullmatch(r"[\w.-]+\.md", str(name or "")):
        return None
    path = pack_dir() / name
    return path if path.is_file() else None

# --- Zip de arquivos e pastas para o chat ---
ZIP_MAX_FILES = 500
ZIP_MAX_BYTES = 50 * 1024 * 1024
_ZIP_BLOCKED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__"}


def project_files(root):
    """Arquivos do projeto (relativos, com '/'): rastreados + novos não ignorados; sem .git, venv e node_modules."""
    root = Path(root)
    found = []
    if is_repo(root):
        done = _git(root, "ls-files", "-z", "-c", "-o", "--exclude-standard")
        found = [p for p in (done.stdout or b"").decode("utf-8", errors="replace").split("\0") if p]
    else:
        for current, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _ZIP_BLOCKED_DIRS]
            found.extend(Path(current, n).relative_to(root).as_posix() for n in names)
    ok = [p for p in found if not (set(p.split("/")) & _ZIP_BLOCKED_DIRS) and (root / p).is_file()]
    return sorted(set(ok))


def _parent_dirs(path):
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def resolve_zip_targets(root, names):
    """Casa nomes (arquivo simples, sufixo, caminho completo ou pasta) com os arquivos do projeto.
    Devolve (arquivos, ignorados, erro)."""
    files = project_files(root)
    dirs = sorted({d for f in files for d in _parent_dirs(f)})
    selected, skipped, ambiguous, missing = [], [], {}, []
    wanted = 0
    for raw in names or []:
        name = str(raw).strip().replace("\\", "/").strip("'\"<>").rstrip("/")
        if name.startswith("./"):
            name = name[2:]
        if not name:
            continue
        wanted += 1
        hits, amb, miss = resolve_names(files, [name])
        if not hits and not amb:
            dir_hits, amb, miss = resolve_names(dirs, [name])
            hits = [f for d in dir_hits for f in files if f.startswith(d + "/")]
        ambiguous.update(amb)
        missing.extend(miss)
        for path in hits:
            if path not in selected:
                selected.append(path)
    if not wanted:
        return [], [], "ERRO: nenhum arquivo ou pasta informado."
    if ambiguous or missing:
        return [], [], _problems_text(ambiguous, missing)
    kept = []
    for path in selected:
        if is_secret_path(path):
            skipped.append(f"{path} (segredo)")
        else:
            kept.append(path)
    if not kept:
        return [], skipped, "ERRO: nada para zipar" + (": " + ", ".join(skipped) if skipped else ".")
    if len(kept) > ZIP_MAX_FILES:
        return [], skipped, f"ERRO: {len(kept)} arquivos passam do limite de {ZIP_MAX_FILES}. Peça uma pasta menor ou nomes específicos."
    total = sum((Path(root) / p).stat().st_size for p in kept)
    if total > ZIP_MAX_BYTES:
        return [], skipped, f"ERRO: {total // (1024 * 1024)} MB passam do limite de {ZIP_MAX_BYTES // (1024 * 1024)} MB. Peça menos arquivos."
    return kept, skipped, None


def build_zip(root, names, hint=""):
    """Zipa os arquivos/pastas pedidos. Devolve dict {path, files, skipped, bytes} ou texto 'ERRO: ...'."""
    root = Path(root)
    files, skipped, error = resolve_zip_targets(root, names)
    if error:
        return error
    base = pack_dir()
    now = time.time()
    for old in base.glob("arquivos_*.zip"):
        try:
            if now - old.stat().st_mtime > 30 * 24 * 3600:
                old.unlink()
        except OSError:
            continue
    label = hint or "-".join(Path(str(n)).stem for n in list(names)[:3])
    slug = re.sub(r"[^a-z0-9]+", "-", str(label).lower())[:40].strip("-") or "arquivos"
    path = base / f"arquivos_{time.strftime('%Y%m%d_%H%M%S')}_{slug}.zip"
    tmp = path.with_name(path.name + ".part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
            for rel in files:
                archive.write(root / rel, arcname=rel)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"path": path, "files": files, "skipped": skipped, "bytes": path.stat().st_size}


def zip_file_path(name):
    if not re.fullmatch(r"[\w.-]+\.zip", str(name or "")):
        return None
    path = pack_dir() / name
    return path if path.is_file() else None
