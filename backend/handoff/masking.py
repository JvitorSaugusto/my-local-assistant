"""Mascara segredos antes de o pacote sair da máquina (Fase B).

Regra de projeto: preferir mascarar de menos a quebrar código. Atribuições só são mascaradas quando o
valor é um literal entre aspas (ou linha estilo .env), então `primary_key=True` e
`os.getenv("DATABASE_URL")` passam intactos.
"""

from __future__ import annotations

import re

_NAME = r"[A-Za-z0-9_.\-]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|DATABASE_URL|DB_URL|DSN)[A-Za-z0-9_.\-]*"
# NOME = "valor" | "nome": "valor" | NOME: 'valor'
_QUOTED = re.compile(rf"""(?P<pre>["']?\b{_NAME}["']?\s*[:=]\s*)(?P<q>["'])(?P<v>[^"'\n]{{6,}})(?P=q)""", re.I)
# linha estilo .env:  NOME=valor  (início da linha, opcionalmente depois do "12: " do dossiê)
_DOTENV = re.compile(rf"""(?m)^(?P<pre>(?:\d+:\s*)?{_NAME}=)(?P<v>[^\s"'#][^\s#]{{5,}})$""", re.I)
_URL_CREDS = re.compile(r"(?P<pre>\b[a-z][a-z0-9+.\-]*://[^\s:/@\"']+):(?P<v>[^\s@/\"']+)@", re.I)
_TOKENS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}"),
]
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
MASK = "***MASCARADO***"


def mask_secrets(text: str) -> tuple[str, int]:
    """(texto mascarado, quantidade de trocas)."""
    count = 0

    def bump(replacement: str):
        def repl(match: re.Match) -> str:
            nonlocal count
            count += 1
            return replacement.format(**match.groupdict())

        return repl

    text = _PEM.sub(bump(MASK + " (chave privada)"), text)
    text = _QUOTED.sub(bump("{pre}{q}" + MASK + "{q}"), text)
    text = _DOTENV.sub(bump("{pre}" + MASK), text)
    text = _URL_CREDS.sub(bump("{pre}:" + MASK + "@"), text)
    for pattern in _TOKENS:
        text = pattern.sub(bump(MASK), text)
    return text, count
