"""Decompõe o pedido do usuário em itens verificáveis e monta as regras de cobertura do gatherer."""
import re

_PATH = re.compile(
    r"(?<![\w/.-])((?:[\w.-]+/)[\w.-]+\.(?:py|js|ts|tsx|jsx|html|css|md|json|bat|cmd|ps1|yaml|yml|toml|sql))\b"
)

GATHERER_COVERAGE_RULES = """COBERTURA DO PEDIDO (obrigatória):
1. O pedido tem vários itens. Trate UM item por vez e só escreva o dossiê quando TODOS os itens tiverem sido pesquisados.
2. Para cada item, termine o dossiê com uma linha: ITEM n: ENCONTRADO (arquivo, linhas A-B) ou ITEM n: NÃO ENCONTRADO (busquei por: ...).
3. Arquivos com mais de 400 linhas (como backend/static/script.js): use search_in_file com os padrões addEventListener|onclick|getElementById|fetch\\( e o nome do botão ou da rota, depois read_file_chunk na linha achada, lendo até o fechamento da função.
4. Handlers anônimos (addEventListener("click", () => {...})) contam como handler: copie o bloco inteiro.
5. Em Trecho Atual Confirmado, copie as linhas EXATAS lidas pelas tools. Proibido usar # ..., // ..., reticências ou pass no lugar de código. Se o trecho for longo, copie mais linhas ou cite só o intervalo lido.
6. Nunca cite função, rota ou arquivo que não tenha aparecido no retorno de uma tool desta execução.
7. Se um item não for achado após buscar, diga NÃO ENCONTRADO. Nunca preencha com suposição."""


def _subitems(what):
    parts = re.split(r",\s*|\s+e\s+(?=o |a |os |as |como )", what)
    return [part.strip(" .;") for part in parts if len(part.strip(" .;")) > 2]


def extract_checklist(message):
    message = message or ""
    matches = list(_PATH.finditer(message))
    items = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(message)
        what = message[match.end():end].strip(" :,-;\n")[:400]
        items.append({"file": match.group(1), "what": what, "subitems": _subitems(what)})
    return items


def render_checklist(items):
    lines = ["CHECKLIST DO PEDIDO (todos os itens precisam ser respondidos):"]
    for number, item in enumerate(items, 1):
        lines.append(f"{number}. {item['file']} -> {item['what']}")
        for sub in item.get("subitems", []):
            lines.append(f"   - {sub}")
    return "\n".join(lines)


def gatherer_coverage_part(message):
    """Texto de sistema para o gatherer quando o pedido cita arquivos; None caso contrário."""
    items = extract_checklist(message)
    if not items:
        return None
    return GATHERER_COVERAGE_RULES + "\n\n" + render_checklist(items)
