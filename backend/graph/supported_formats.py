"""Fatos sobre as tools de leitura, para o heavy responder sem inventar extensões."""
import re

READ_SUPPORT_FACTS = """FATOS SOBRE AS TOOLS DE LEITURA (verificados no código; ao falar de formatos suportados use SOMENTE isto):
- Texto: qualquer arquivo de texto é lido como UTF-8 (com plano B cp1252 e latin-1), seja qual for a extensão. Isso inclui .py, .js, .html, .css, .json, .md, .yaml, .sql, .sh, .bat, .cmd, .ps1 e arquivos sem extensão.
- PDF: lido com pypdf, só se tiver camada de texto (scans e PDFs com senha dão erro).
- DOCX: lido direto do zip (parágrafos, títulos e tabelas).
- Bloqueados: as pastas .git, .venv, venv, node_modules, __pycache__ e arquivos .env (só .env.example, .env.sample e .env.template passam).
- Binários (imagens, vídeos, .exe, .zip) não são lidos como texto.
- read_file_content lê até 400 linhas; acima disso use read_file_chunk e search_in_file.
Não liste extensões além das citadas acima e nunca diga que um arquivo de texto como .bat não é suportado."""

_ASK_RE = re.compile(
    r"(?i)extens|formatos?\b|tipos? de arquivo|consegue ler|suporte (?:de|a|para) (?:leitura|arquivo)|l[eê] (?:arquivos? )?\.?(?:bat|pdf|docx|json|txt)"
)


def asks_about_read_support(text):
    return bool(_ASK_RE.search(text or ""))
