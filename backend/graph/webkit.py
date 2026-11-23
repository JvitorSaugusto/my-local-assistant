"""Pesquisa na web, leitura de páginas, data/hora e cálculo seguro, SÓ com a biblioteca padrão.

- Pesquisa: SearxNG (WEB_SEARXNG_URL, ex.: http://localhost:8080) se configurado; senão DuckDuckGo (html).
- Leitura de página: só http/https e só endereços PÚBLICOS (bloqueia localhost/rede interna, inclusive em redirecionamentos).
- Cache em memória (WEB_CACHE_SECONDS, padrão 600) e limites de tamanho/tempo.
Desligar tudo: WEB_SEARCH_ENABLED=0 no .env.
"""

from __future__ import annotations

import ast
import gzip
import html as html_lib
import ipaddress
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime
from html.parser import HTMLParser

WEB_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "1") == "1"
USER_AGENT = "Mozilla/5.0 (compatible; AssistenteLocal/1.0)"


def web_enabled() -> bool:
    try:
        from backend.api.settings_store import get_setting

        return bool(get_setting("web_search_enabled", os.getenv("WEB_SEARCH_ENABLED", "1") == "1"))
    except Exception:
        return os.getenv("WEB_SEARCH_ENABLED", "1") == "1"
_CACHE: dict[str, tuple[float, object]] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _cache_get(key: str):
    item = _CACHE.get(key)
    if item and time.time() - item[0] < _env_int("WEB_CACHE_SECONDS", 600):
        return item[1]
    return None


def _cache_put(key: str, value) -> None:
    if len(_CACHE) >= 64:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.time(), value)


# ----------------------------------------------------------------------
# Segurança de URL
# ----------------------------------------------------------------------

def is_public_url(url: str) -> tuple[bool, str]:
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False, "URL inválida"
    if parts.scheme not in ("http", "https"):
        return False, "só são aceitos links http/https"
    host = parts.hostname
    if not host:
        return False, "URL sem endereço"
    if os.getenv("WEB_ALLOW_PRIVATE", "0") == "1":
        return True, ""
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False, "endereço não encontrado"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, "endereço interno bloqueado"
    return True, ""


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, why = is_public_url(newurl)
        if not ok:
            raise urllib.error.URLError(f"redirecionamento bloqueado ({why})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get_bytes(url: str, timeout: int = 15, max_bytes: int = 1_500_000, headers: dict | None = None,
                   data: bytes | None = None, validate: bool = True) -> tuple[str, str, bytes, str | None]:
    """Devolve (url final, content-type, bytes descompactados, charset). Levanta OSError/URLError em falha."""
    if validate:
        ok, why = is_public_url(url)
        if not ok:
            raise OSError(why)
    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6", "Accept-Encoding": "gzip, deflate", **(headers or {})},
    )
    opener = urllib.request.build_opener(_SafeRedirect() if validate else urllib.request.HTTPRedirectHandler())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(max_bytes + 1)[:max_bytes]
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        content_type = response.headers.get("Content-Type") or ""
        final_url = response.geturl()
        charset = response.headers.get_content_charset()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    elif "deflate" in encoding:
        try:
            raw = zlib.decompress(raw)
        except Exception:
            pass
    return final_url, content_type, raw, charset


def _decode_bytes(raw: bytes, charset: str | None = None) -> str:
    if not charset:
        match = re.search(rb'charset=["\']?([\w-]+)', raw[:4000])
        charset = match.group(1).decode("ascii", "ignore") if match else "utf-8"
    try:
        return raw.decode(charset, "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


def http_get(url: str, timeout: int = 15, max_bytes: int = 1_500_000, headers: dict | None = None,
             data: bytes | None = None, validate: bool = True) -> tuple[str, str, str]:
    """Devolve (url final, content-type, texto). Levanta OSError/URLError em falha."""
    final_url, content_type, raw, charset = http_get_bytes(url, timeout=timeout, max_bytes=max_bytes, headers=headers, data=data, validate=validate)
    return final_url, content_type, _decode_bytes(raw, charset)


# ----------------------------------------------------------------------
# HTML -> texto
# ----------------------------------------------------------------------

_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "iframe", "template", "head"}
_BLOCK = {"p", "div", "br", "li", "tr", "section", "article", "blockquote", "table", "ul", "ol", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in _SKIP and tag != "head":
            self._skip += 1
        if self._skip:
            return
        if tag in _BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3", "h4"):
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP and tag != "head" and self._skip:
            self._skip -= 1
        if not self._skip and tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str, max_chars: int = 6000) -> tuple[str, str]:
    """(título, texto limpo) de uma página HTML."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    text = "".join(parser.parts)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    body = "\n".join(cleaned).strip()
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n[... texto cortado ...]"
    return re.sub(r"\s+", " ", parser.title).strip(), body


_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_youtube_video_id(url: str) -> str | None:
    """Extrai o ID de 11 caracteres de links do YouTube (watch, youtu.be, shorts, live, embed)."""
    try:
        parts = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "youtu.be":
        cand = parts.path.strip("/").split("/")[0]
        return cand if _YT_ID_RE.match(cand) else None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parts.path == "/watch":
            cand = (urllib.parse.parse_qs(parts.query).get("v") or [""])[0]
            return cand if _YT_ID_RE.match(cand) else None
        segs = [s for s in parts.path.split("/") if s]
        if len(segs) >= 2 and segs[0] in ("shorts", "embed", "live", "v"):
            cand = segs[1]
            return cand if _YT_ID_RE.match(cand) else None
    return None


def _format_ts(seconds: float) -> str:
    sec = max(0, int(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _extract_json_object(text: str, marker: str) -> dict | None:
    import json

    idx = text.find(marker)
    if idx == -1:
        return None
    start = text.find("{", idx + len(marker))
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _parse_caption_xml(raw_xml: str) -> list[tuple[float, str]]:
    from xml.etree import ElementTree as ET

    entries: list[tuple[float, str]] = []
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return entries
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag == "text":
            start = float(node.attrib.get("start") or 0.0)
            txt = re.sub(r"\s+", " ", html_lib.unescape("".join(node.itertext()))).strip()
            if txt:
                entries.append((start, txt))
        elif tag == "p":
            start = float(node.attrib.get("t") or 0.0) / 1000.0
            txt = re.sub(r"\s+", " ", html_lib.unescape("".join(node.itertext()))).strip()
            if txt:
                entries.append((start, txt))
    return entries


def _format_transcript_entries(entries: list[tuple[float, str]], max_chars: int) -> str:
    blocks: list[str] = []
    cur_ts = ""
    cur_parts: list[str] = []
    cur_len = 0
    for start, text in entries:
        if not cur_ts:
            cur_ts = _format_ts(start)
        cur_parts.append(text)
        cur_len += len(text) + 1
        if cur_len >= 280:
            blocks.append(f"[{cur_ts}] " + " ".join(cur_parts))
            cur_ts, cur_parts, cur_len = "", [], 0
    if cur_parts:
        blocks.append(f"[{cur_ts}] " + " ".join(cur_parts))
    body = "\n\n".join(blocks)
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n[... transcrição cortada ...]"
    return body


def _pick_caption_track(tracks: list[dict], preferred: tuple[str, ...] = ("pt-br", "pt", "en")) -> dict | None:
    if not tracks:
        return None
    for lang in preferred:
        manual = [t for t in tracks if str(t.get("languageCode") or "").lower().startswith(lang) and t.get("kind") != "asr"]
        if manual:
            return manual[0]
        auto = [t for t in tracks if str(t.get("languageCode") or "").lower().startswith(lang)]
        if auto:
            return auto[0]
    return tracks[0]


def fetch_youtube_transcript(url: str, max_chars: int = 12000) -> str:
    """Extrai título, canal e transcrição (legendas) de um vídeo do YouTube."""
    max_chars = max(500, min(int(max_chars or 12000), 25000))
    vid = extract_youtube_video_id(url)
    if not vid:
        return f"ERRO: '{url}' não é um link de vídeo do YouTube válido."
    key = f"yt:{vid}:{max_chars}"
    cached = _cache_get(key)
    if cached:
        return cached  # type: ignore[return-value]

    watch_url = f"https://www.youtube.com/watch?v={vid}"
    timeout = _env_int("WEB_TIMEOUT", 15)
    title = ""
    author = ""
    entries: list[tuple[float, str]] = []
    lang_used = ""

    try:
        _, _, raw_html, charset = http_get_bytes(
            f"{watch_url}&hl=pt",
            timeout=timeout,
            max_bytes=2_500_000,
            headers={"Cookie": "CONSENT=YES+1"},
            validate=False,
        )
        page = _decode_bytes(raw_html, charset)
        player = _extract_json_object(page, "ytInitialPlayerResponse =") or _extract_json_object(page, '"ytInitialPlayerResponse":')
        if player:
            details = player.get("videoDetails") or {}
            title = str(details.get("title") or "").strip()
            author = str(details.get("author") or "").strip()
            tracks = ((player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}).get("captionTracks") or []
            chosen = _pick_caption_track(tracks)
            if chosen and chosen.get("baseUrl"):
                lang_used = str(chosen.get("languageCode") or "")
                _, _, cap_bytes, cap_charset = http_get_bytes(str(chosen["baseUrl"]), timeout=timeout, max_bytes=2_000_000, validate=False)
                entries = _parse_caption_xml(_decode_bytes(cap_bytes, cap_charset))
    except Exception as exc:
        if not entries:
            err_note = str(exc)
        else:
            err_note = ""
    else:
        err_note = ""

    if not entries:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-not-found]

            raw_items = YouTubeTranscriptApi.get_transcript(vid, languages=["pt", "pt-BR", "en"])
            entries = [(float(i.get("start") or 0.0), str(i.get("text") or "").strip()) for i in raw_items if str(i.get("text") or "").strip()]
        except Exception:
            pass

    if not entries:
        extra = f" ({err_note})" if err_note else ""
        return f"ERRO: não consegui obter legendas/transcrição para {watch_url}{extra}. O vídeo pode não ter legendas disponíveis."

    header = [f"Título: {title or '(sem título)'}"]
    if author:
        header.append(f"Canal: {author}")
    if lang_used:
        header.append(f"Idioma da legenda: {lang_used}")
    header.append(f"URL: {watch_url}")
    result = "\n".join(header) + "\n\n" + _format_transcript_entries(entries, max_chars)
    _cache_put(key, result)
    return result


def _extract_pdf_bytes(raw: bytes, max_chars: int = 6000, max_pages: int = 80) -> str:
    from io import BytesIO

    try:
        from pypdf import PdfReader
    except ImportError:
        return "ERRO: leitura de PDF online indisponível (instale 'pypdf')."
    try:
        reader = PdfReader(BytesIO(raw))
    except Exception as exc:
        return f"ERRO ao ler PDF online: {exc}"
    if reader.is_encrypted:
        return "ERRO: o PDF online está protegido por senha."
    parts: list[str] = []
    total_pages = len(reader.pages)
    used = 0
    for idx, page in enumerate(reader.pages[:max_pages], start=1):
        txt = (page.extract_text() or "").strip()
        if not txt:
            continue
        block = f"[página {idx}]\n{txt}"
        parts.append(block)
        used += len(block) + 2
        if used >= max_chars + 500:
            break
    if not parts:
        return "ERRO: o PDF online não possui camada de texto extraível (provavelmente é escaneado)."
    body = "\n\n".join(parts)
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + f"\n[... PDF com {total_pages} página(s); texto cortado ...]"
    return body


def fetch_page(url: str, max_chars: int = 6000) -> str:
    max_chars = max(500, min(int(max_chars or 6000), 20000))
    if extract_youtube_video_id(url):
        return fetch_youtube_transcript(url, max_chars=max_chars)
    key = f"page:{url}:{max_chars}"
    cached = _cache_get(key)
    if cached:
        return cached  # type: ignore[return-value]
    try:
        final_url, content_type, raw, charset = http_get_bytes(
            url,
            timeout=_env_int("WEB_TIMEOUT", 15),
            max_bytes=_env_int("WEB_FETCH_MAX_BYTES", 8_000_000),
        )
    except Exception as exc:
        return f"ERRO ao abrir {url}: {exc}"
    kind = content_type.lower()
    if "pdf" in kind or raw.startswith(b"%PDF-"):
        body = _extract_pdf_bytes(raw, max_chars=max_chars)
        result = body if body.startswith("ERRO:") else f"Tipo: PDF online\nURL: {final_url}\n\n{body}"
        if not result.startswith("ERRO:"):
            _cache_put(key, result)
        return result
    text = _decode_bytes(raw, charset)
    if "html" in kind or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, body = html_to_text(text, max_chars)
        result = f"Título: {title or '(sem título)'}\nURL: {final_url}\n\n{body or '(página sem texto legível)'}"
    else:
        body = text if len(text) <= max_chars else text[:max_chars] + "\n[... texto cortado ...]"
        result = f"URL: {final_url}\n\n{body}"
    _cache_put(key, result)
    return result


# ----------------------------------------------------------------------
# Pesquisa
# ----------------------------------------------------------------------

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def _unwrap_ddg(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    query = urllib.parse.urlsplit(href).query
    if "uddg=" in query:
        values = urllib.parse.parse_qs(query).get("uddg")
        if values:
            return values[0]
    return href


class _DDGParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._mode: str | None = None
        self._buf: list[str] = []
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs_d = dict(attrs)
        classes = (attrs_d.get("class") or "").split()
        if "result__a" in classes:
            self._mode, self._buf, self._href = "title", [], attrs_d.get("href") or ""
        elif "result__snippet" in classes:
            self._mode, self._buf = "snippet", []

    def handle_data(self, data):
        if self._mode:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self._mode:
            return
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if self._mode == "title":
            url = _unwrap_ddg(self._href)
            if url and "duckduckgo.com/y.js" not in url:
                self.results.append({"title": text, "url": url, "snippet": ""})
        elif self.results and not self.results[-1]["snippet"]:
            self.results[-1]["snippet"] = text
        self._mode = None


def parse_ddg_html(page: str) -> list[dict]:
    parser = _DDGParser()
    try:
        parser.feed(page)
        parser.close()
    except Exception:
        pass
    return [r for r in parser.results if r["url"].startswith("http")]


def parse_searxng_json(data: dict) -> list[dict]:
    return [
        {"title": _clean(r.get("title", "")), "url": r.get("url", ""), "snippet": _clean(r.get("content", ""))}
        for r in (data.get("results") or [])
        if r.get("url")
    ]


def search_web(query: str, max_results: int = 5) -> tuple[list[dict], str]:
    """(resultados, nome da fonte). Levanta RuntimeError com mensagem clara em falha."""
    import json

    query = (query or "").strip()
    if not query:
        raise RuntimeError("pesquisa vazia")
    max_results = max(1, min(int(max_results or 5), 10))
    key = f"search:{query}:{max_results}"
    cached = _cache_get(key)
    if cached:
        return cached  # type: ignore[return-value]
    timeout = _env_int("WEB_TIMEOUT", 15)
    searx = (os.getenv("WEB_SEARXNG_URL") or "").rstrip("/")
    try:
        if searx:
            url = f"{searx}/search?" + urllib.parse.urlencode({"q": query, "format": "json", "language": "pt-BR"})
            _, _, body = http_get(url, timeout=timeout, validate=False)
            results, source = parse_searxng_json(json.loads(body)), "SearxNG"
        else:
            data = urllib.parse.urlencode({"q": query, "kl": "br-pt"}).encode()
            _, _, body = http_get("https://html.duckduckgo.com/html/", timeout=timeout, data=data, validate=False)
            results, source = parse_ddg_html(body), "DuckDuckGo"
            if not results and ("anomaly" in body.lower() or "captcha" in body.lower()):
                raise RuntimeError("o DuckDuckGo bloqueou a consulta (muitas buscas). Configure WEB_SEARXNG_URL no .env.")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"falha ao pesquisar ({type(exc).__name__}: {exc})")
    results = results[:max_results]
    out = (results, source)
    if results:
        _cache_put(key, out)
    return out


def format_results(query: str, results: list[dict], source: str) -> str:
    if not results:
        return f"Nenhum resultado para: {query}"
    lines = [f"Resultados para «{query}» (fonte: {source}). Abra as melhores com web_fetch antes de afirmar detalhes:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title'] or r['url']}\n   {r['url']}" + (f"\n   {r['snippet']}" if r["snippet"] else ""))
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Data, hora e cálculo
# ----------------------------------------------------------------------

_WEEKDAYS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _now() -> datetime:
    tz = os.getenv("ASSISTANT_TZ")
    if tz:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz))
        except Exception:
            pass
    return datetime.now().astimezone()


def today_label(now: datetime | None = None) -> str:
    now = now or _now()
    return f"{_WEEKDAYS[now.weekday()]}, {now.day} de {_MONTHS[now.month - 1]} de {now.year}"


def now_text(now: datetime | None = None) -> str:
    now = now or _now()
    offset = now.strftime("%z")
    return f"{today_label(now)}, {now:%H:%M} (UTC{offset[:3]}:{offset[3:]})" if offset else f"{today_label(now)}, {now:%H:%M}"


_CALC_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil,
}
_CALC_CONST = {"pi": math.pi, "e": math.e}


def _eval(node, budget: list[int]):
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("expressão grande demais")
    if isinstance(node, ast.Expression):
        return _eval(node.body, budget)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CALC_CONST:
        return _CALC_CONST[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand, budget)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, budget), _eval(node.right, budget)
        op = node.op
        if isinstance(op, ast.Add):
            result = left + right
        elif isinstance(op, ast.Sub):
            result = left - right
        elif isinstance(op, ast.Mult):
            result = left * right
        elif isinstance(op, ast.Div):
            result = left / right
        elif isinstance(op, ast.FloorDiv):
            result = left // right
        elif isinstance(op, ast.Mod):
            result = left % right
        elif isinstance(op, ast.Pow):
            if abs(right) > 1000 or abs(left) > 1e6:
                raise ValueError("potência grande demais")
            result = left ** right
        else:
            raise ValueError("operador não permitido")
        if isinstance(result, int) and result.bit_length() > 4000:
            raise ValueError("número grande demais")
        return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _CALC_FUNCS and not node.keywords:
        return _CALC_FUNCS[node.func.id](*[_eval(arg, budget) for arg in node.args])
    raise ValueError("expressão não permitida")


def safe_calc(expression: str) -> str:
    expr = (expression or "").strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expr or len(expr) > 300:
        return "ERRO: expressão vazia ou longa demais."
    try:
        value = _eval(ast.parse(expr, mode="eval"), [100])
    except ZeroDivisionError:
        return "ERRO: divisão por zero."
    except Exception as exc:
        return f"ERRO: não consegui calcular ({exc}). Use números, + - * / // % ** ( ) e sqrt, round, min, max, log, sin, cos."
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    shown = f"{value:.12g}" if isinstance(value, float) else str(value)
    return f"{expression.strip()} = {shown}"


# ----------------------------------------------------------------------
# Links e verificação
# ----------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".,;:!?*") for u in _URL_RE.findall(text or "")]


def strip_unverified_urls(answer: str, known_text: str) -> str:
    """Remove links da resposta que NÃO apareceram nos resultados das ferramentas (links inventados)."""
    known = {u.rstrip("/").lower() for u in urls_in(known_text)}

    def check(match: re.Match) -> str:
        url = match.group(0).rstrip(".,;:!?*")
        tail = match.group(0)[len(url):]
        norm = url.rstrip("/").lower()
        if any(norm == k or k.startswith(norm) or norm.startswith(k) for k in known):
            return match.group(0)
        return "[link não verificado removido]" + tail

    return _URL_RE.sub(check, answer or "")
