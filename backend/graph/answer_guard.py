"""Checagens por código sobre a resposta final do heavy (não chamam modelo)."""
import re
from collections import Counter

_META_SUBS = [
    (r"(?i)\bo\s+dossi[êe]\s+n[ãa]o\s+(?:cont[ée]m|menciona|indica|mostra)\b", "Não encontrei"),
    (r"(?i)\b(?:segundo|conforme|de acordo com|com base n[oa]s?|a partir d[oa]s?)\s+(?:o\s+)?dossi[êe]\b[,:]?\s*", ""),
    (r"(?i)\bno\s+dossi[êe]\b", "no projeto"),
    (r"(?i)\bdo\s+dossi[êe]\b", "do projeto"),
    (r"(?i)\bdossi[êe]\b", "projeto"),
    (r"(?i)\bcontext gatherer\b", "leitura do projeto"),
    (r"(?i)\bcoletor\b", "leitura do projeto"),
    (r"(?i)\btool calls?\b", "leituras"),
]

_RAW_RE = re.compile(r"(?i)retorno bruto|sa[ií]da (?:crua|bruta)|output (?:bruto|cru)|cole exatamente")
_EXT_LIKE = re.compile(r"^\.[A-Za-z0-9]{1,12},?")
_PATH_EXTS = (
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".txt", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".sql", ".sh", ".bat", ".cmd", ".ps1", ".csv", ".xml", ".mako", ".pdf", ".docx",
)
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_IGNORED_NAMES = {"True", "False", "None", "self", "cls", "null", "true", "false", "async", "await", "return"}
_NOT_CONFIRMED = " (não confirmado no código)"


def wants_raw_output(text):
    return bool(_RAW_RE.search(text or ""))


def _split_fences(text):
    """Devolve [(trecho, dentro_de_bloco_de_codigo)]."""
    parts = (text or "").split("```")
    return [(part, index % 2 == 1) for index, part in enumerate(parts)]


def _join_fences(pieces):
    out = []
    for index, (part, _inside) in enumerate(pieces):
        out.append(part)
        if index < len(pieces) - 1:
            out.append("```")
    return "".join(out)


def has_meta_references(text):
    return any(re.search(pattern, text or "") for pattern, _ in _META_SUBS)


def scrub_meta_references(text):
    pieces = []
    for part, inside in _split_fences(text):
        if not inside:
            for pattern, repl in _META_SUBS:
                part = re.sub(pattern, repl, part)
        pieces.append((part, inside))
    return _join_fences(pieces)


def detect_repetition(text, max_run=20):
    tokens = re.findall(r"\S+", text or "")
    if len(tokens) < 40:
        return False
    run = 1
    for prev, cur in zip(tokens, tokens[1:]):
        run = run + 1 if cur == prev else 1
        if run >= max_run:
            return True
    if sum(1 for token in tokens if _EXT_LIKE.match(token)) > 120:
        return True
    if len(tokens) >= 200 and len(set(tokens)) / len(tokens) < 0.25:
        return True
    grams = Counter(zip(tokens, tokens[1:], tokens[2:], tokens[3:]))
    return bool(grams) and grams.most_common(1)[0][1] >= 40


def _is_code_like(name):
    return "_" in name or "." in name or re.search(r"[a-z][A-Z]", name) is not None


def extract_identifiers(text):
    found = []
    for part, inside in _split_fences(text):
        if inside:
            continue
        for raw in re.findall(r"`([^`\n]{2,120})`", part):
            item = re.sub(r"\(.*\)$", "", raw.strip()).strip()
            if not item or item in _IGNORED_NAMES or " " in item:
                continue
            if item.startswith("/"):
                kind = "route"
            elif "/" in item or item.lower().endswith(_PATH_EXTS):
                kind = "path"
            elif _NAME_RE.match(item) and _is_code_like(item):
                kind = "name"
            else:
                continue
            if (item, kind) not in found:
                found.append((item, kind))
    return found


def _route_known(route, corpus):
    if route.split("{")[0].rstrip("/") in corpus:
        return True
    segments = [seg for seg in route.split("/") if seg and not seg.startswith("{")]
    return bool(segments) and ("/" + segments[-1]) in corpus


def find_invalid_identifiers(answer, corpus, check_names=True):
    corpus = corpus or ""
    invalid = []
    for item, kind in extract_identifiers(answer):
        if kind == "name":
            ok = (not check_names) or item in corpus or item.split(".")[-1] in corpus
        elif kind == "route":
            ok = _route_known(item, corpus)
        else:
            ok = item.replace(chr(92), "/").split("/")[-1] in corpus
        if not ok and item not in invalid:
            invalid.append(item)
    return invalid


def ground_answer(answer, corpus, check_names=True):
    invalid = find_invalid_identifiers(answer, corpus, check_names)
    pieces = []
    for part, inside in _split_fences(answer):
        if not inside:
            for item in invalid:
                pattern = "`" + re.escape(item) + r"(?:\(\))?`"
                part = re.sub(pattern, lambda m: m.group(0) + _NOT_CONFIRMED, part)
        pieces.append((part, inside))
    return _join_fences(pieces), invalid


def build_answer_corpus(dossier, repo_map, stack, messages, trace):
    parts = [dossier or "", repo_map or "", stack or "", str(trace or "")]
    for message in messages or []:
        if getattr(message, "type", "") == "human" and isinstance(message.content, str):
            parts.append(message.content)
    return "\n".join(parts)


def finalize_answer(answer, corpus, check_names=True):
    text = scrub_meta_references(answer)
    degenerate = detect_repetition(text)
    text, invalid = ground_answer(text, corpus, check_names)
    return {"text": text, "invalid": invalid, "degenerate": degenerate}
